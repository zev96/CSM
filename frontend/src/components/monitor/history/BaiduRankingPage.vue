<script setup lang="ts">
/**
 * 百度关键词工作台 —— 与知乎问题工作台同款双卡布局。
 * 左：富任务表（搜索关键词 / 上次 / 变化 / 状态 / 操作）
 * 右：3 KPI + sparkline + 每关键词折叠结果段
 */
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRouter } from "vue-router";
import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import { subscribe } from "@/api/client";
import Sparkline from "@/components/ui/Sparkline.vue";
import Pill from "@/components/ui/Pill.vue";
import Icon from "@/components/ui/Icon.vue";
import Btn from "@/components/ui/Btn.vue";
import LineChart from "./LineChart.vue";
import AlertDetailModal from "@/components/monitor/AlertDetailModal.vue";

// ──────────────────────────── types ────────────────────────────

interface BaiduResultRow {
  rank: number;
  title: string;
  url: string;
  host: string;
  matches_brand: boolean;
  matched_brand: string | null;
  source: "http" | "browser";
  content_preview: string;
  fetch_error: string | null;
}

interface BaiduPerKeyword {
  keyword: string;
  serp_url: string;
  default_results: BaiduResultRow[];
  news_results: BaiduResultRow[];
  default_matched_count: number;
  default_first_rank: number;
  news_first_rank: number;
  news_present: boolean;
  fetch_error: string | null;
}

interface BaiduMetric {
  target_brand: string;
  search_keywords: string[];
  engine: string;
  headless: boolean;
  captcha_hit: boolean;
  keywords: BaiduPerKeyword[];
  total_keywords: number;
  matched_keywords: number;
  total_default_matches: number;
  best_default_first_rank: number;
}

interface TaskItem {
  id: number;
  name: string;
  type: string;
  config: { search_keywords: string[]; target_brand: string };
  last_check_at: string | null;
  last_status: string | null;
  schedule_cron?: string;
}

interface ResultItem {
  task_id: number;
  checked_at: string;
  status: string;
  rank: number;
  metric: BaiduMetric | null;
  error_message: string | null;
}

// ──────────────────────────── emits ────────────────────────────

const emit = defineEmits<{
  (e: "add-task"): void;
  (e: "batch-import"): void;
  (e: "edit-task", task: TaskItem): void;
}>();

// ──────────────────────────── store / composables ────────────────────────────

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();
const toast = useToast();
// Cross-page truth for running tasks + cancel API. The store owns the
// SSE subscription that updates runningTaskIds + taskProgress; this
// component subscribes to SSE only for *page-specific* reactions
// (history reload on finished). On mount we also force a /running
// hydrate so navigating away+back doesn't leave stale state.
const monitorStatus = useMonitorStatus();

// ──────────────────────────── state ────────────────────────────

const tasks = ref<TaskItem[]>([]);
const selectedId = ref<number | null>(null);
// Selected keyword index in Level 2 (for the per-keyword ranking detail panel)
const selectedKeywordIdx = ref<number | null>(null);
const history = ref<ResultItem[]>([]);
const loadingTasks = ref(false);
const loadingHistory = ref(false);
const runningNow = ref(false);
// Level 1 右卡 sticky preview —— click on row OR hover updates this; mouse-leave
// does NOT clear (so the right-card preview is stable). Defaults to first task.
const previewId = ref<number | null>(null);
// Backing map: per-task recent history (limit 14) for Level 1
// 状态 column + 14-day sparkline. Lazy-filled in loadTasks.
const taskHistories = ref<Record<number, ResultItem[]>>({});
// runningTaskIds / taskProgress now live in the monitorStatus store —
// see top of this script. The proxies below let the existing template
// keep its `isRunning(t.id)` / `taskProgress[t.id]` semantics without
// rewriting every binding.
function isRunning(taskId: number): boolean {
  return monitorStatus.isRunning(taskId);
}
const taskProgress = computed(() => monitorStatus.taskProgress);

// markRunning / clearRunning delegate to the store — local helpers kept
// only for the optimistic mark we still do in runNow before the SSE
// `started` event arrives. The store dedupes so double-marks are safe.
function markRunning(taskId: number): void {
  monitorStatus.markRunning(taskId);
}
function clearRunning(taskId: number): void {
  monitorStatus.clearRunning(taskId);
}

// ──────────────────────────── derived ────────────────────────────

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedId.value) ?? null,
);

// Level 1 右卡预览：previewId 由 row 点击 / hover 更新；fallback 到第一条
const previewTask = computed<TaskItem | null>(() => {
  if (previewId.value !== null) {
    const t = tasks.value.find((x) => x.id === previewId.value);
    if (t) return t;
  }
  return tasks.value[0] ?? null;
});

// 该 preview task 的最近 14 份历史结果（按时间倒序，跟 list_results 一致）
const previewHistory = computed<ResultItem[]>(() => {
  const t = previewTask.value;
  if (!t) return [];
  return taskHistories.value[t.id] ?? [];
});

// preview task 的 ideal_rank（与 Level 2 同一字段，默认 5）
const previewIdealRank = computed<number>(() => {
  const v = (previewTask.value?.config as any)?.ideal_rank;
  return typeof v === 'number' && v > 0 ? v : 5;
});

/**
 * 一份 result 里满足「理想卡位」的关键词数 ——
 * 公式：keyword.default_matched_count + (news_present ? news_matched_count : 0) >= ideal_rank
 */
function _idealCountForMetric(metric: BaiduMetric | null, idealN: number): number {
  if (!metric || !Array.isArray(metric.keywords)) return 0;
  let n = 0;
  for (const kw of metric.keywords) {
    const def = Number(kw.default_matched_count) || 0;
    const news = kw.news_present
      ? kw.news_results.filter((r) => r.matches_brand).length
      : 0;
    if (def + news >= idealN) n += 1;
  }
  return n;
}

/**
 * 把 chronological-ordered 的历史记录按"本地日历日"聚合到长度 totalDays 的
 * 固定窗口里，覆盖 [today-(totalDays-1), today]（含今天）。
 *
 * 设计要点：
 * - 同一天有多次跑 → 取**当天最后一次**（chronological 顺序保证后写覆盖）。
 * - 缺失天 → record=null，调用方决定是用 null 画 gap（LineChart）还是
 *   用 0 占位（Sparkline，因为 Sparkline 的 points: number[] 不接受 null）。
 * - 输出顺序永远是 chronological（最旧 → 最新），跟 chart x 轴方向一致。
 *
 * 之前 sparkPoints/chartLabels 直接把 raw history 铺平显示，结果当天连
 * 跑 N 次时 14 天窗口里全是今天的 N 个点，N 个 label 全是 "MM-DD"（同一
 * 天）—— 用户期望的"14 天连续日历"被压扁成了一天。这个 helper 把"按数据
 * 点排"换成"按日历日分桶"，跟知乎页面 daily_series 的契约对齐。
 */
function bucketByCalendarDay<T extends { checked_at: string }>(
  history: T[],
  totalDays: number = 14,
): Array<{ iso: string; label: string; record: T | null }> {
  const buckets = new Map<string, T>();
  for (const r of history) {
    const d = new Date(r.checked_at);
    if (Number.isNaN(d.getTime())) continue;
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    buckets.set(iso, r); // 同日 → 后写赢（chronological 即时间最晚）
  }
  const out: Array<{ iso: string; label: string; record: T | null }> = [];
  const now = new Date();
  for (let i = totalDays - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    out.push({
      iso,
      label: `${mm}-${dd}`,
      record: buckets.get(iso) ?? null,
    });
  }
  return out;
}

/**
 * preview task 的 14 天日历窗口 —— Level 1 sparkline 数据源。
 * previewHistory 是 newest-first；先 reverse 成 chronological 后再分桶。
 */
const previewCalendarBuckets = computed(() =>
  bucketByCalendarDay([...previewHistory.value].reverse(), 14),
);

// preview task 的 14 天 sparkline：满足理想卡位的关键词数量随时间变化
// 缺失天 → null，LineChart 在 null 处画 gap（spanGaps 默认 false）。
const previewSparkPoints = computed<(number | null)[]>(() => {
  const idealN = previewIdealRank.value;
  return previewCalendarBuckets.value.map((b) =>
    b.record ? _idealCountForMetric(b.record.metric, idealN) : null,
  );
});

/**
 * LineChart-ready x-axis labels —— 14 个 "MM-DD" 字符串，对应 14 个日历日
 * （today-13 → today）。跟 previewSparkPoints 长度一致；缺失天的位置 label
 * 仍然展示（让用户看到完整时间窗口），只是该位置数据点为 null。
 */
const previewChartLabels = computed<string[]>(() =>
  previewCalendarBuckets.value.map((b) => b.label),
);

/**
 * LineChart series wrapper —— 单序列，颜色用 primary 深橙（跟整页主色调一致）。
 * label 文字用作 tooltip 前缀（外部不显示 legend，BaiduSEOAnalytics 同款）。
 */
const previewChartSeries = computed(() => [
  {
    label: "理想卡位关键词数",
    color: "#ee6a2a",
    data: previewSparkPoints.value,
  },
]);

/**
 * Level 1 「状态」列 —— 基于该任务最新一份 result：
 *   理想关键词数 / 总关键词数 ≥ 70% → 正常 (ok)
 *   < 70% → 警报 (alert)
 *   无历史 / captcha / fail → 走原有失败/未跑分支
 */
// ──────────────────────────── Baidu alert hero ───────────────────────
// 触发条件：任务的「理想率」< 70% 即为「警报」状态（与 taskOverallStatus
// 同公式）。多条任务命中 → 用 baiduAlertIdx 翻页查看每一条。

interface BaiduAlertHero {
  taskId: number;
  taskName: string;
  missingCurrent: number;
  missingPrev: number | null;
  missingDelta: number;
  // 卡位为 0 的关键词（重点关注）
  critical: Array<{
    keyword: string;
    placedCount: number;
    placedCountPrev: number | null;
    drop: number;
  }>;
  // 14 天未达理想关键词数序列（chronological）
  sparkPoints: number[];
  sparkAxis: string[];
}

/** 一份 result.metric 里"卡位为 0"的关键词条数计算辅助。 */
function _missingForMetric(metric: BaiduMetric | null, idealN: number): number {
  if (!metric || !Array.isArray(metric.keywords)) return 0;
  let n = 0;
  for (const kw of metric.keywords) {
    const def = Number(kw.default_matched_count) || 0;
    const news = kw.news_present
      ? kw.news_results.filter((r) => r.matches_brand).length
      : 0;
    if (def + news < idealN) n += 1;
  }
  return n;
}

/** Per-task baidu alert summary used by the hero + modal. */
function _buildBaiduAlertHero(task: TaskItem): BaiduAlertHero | null {
  const hist = taskHistories.value[task.id] ?? [];
  const latest = hist[0];
  if (!latest || !latest.metric) return null;
  const idealN = (task.config as any)?.ideal_rank ?? 5;
  const missingCurrent = _missingForMetric(latest.metric, idealN);
  // 阈值与 taskOverallStatus 一致：未达理想 > 60% 才算 alert
  const total = latest.metric.keywords?.length ?? 0;
  if (total === 0 || missingCurrent / total <= 0.6) return null;

  const prev = hist[1];
  const missingPrev = prev?.metric ? _missingForMetric(prev.metric, idealN) : null;

  // 卡位为 0 的关键词 + 下降幅度
  const prevByKw = new Map<string, number>();
  if (prev?.metric?.keywords) {
    for (const kw of prev.metric.keywords) {
      const def = Number(kw.default_matched_count) || 0;
      const news = kw.news_present ? kw.news_results.filter((r) => r.matches_brand).length : 0;
      prevByKw.set(kw.keyword, def + news);
    }
  }
  const critical: BaiduAlertHero["critical"] = [];
  for (const kw of latest.metric.keywords ?? []) {
    const def = Number(kw.default_matched_count) || 0;
    const news = kw.news_present ? kw.news_results.filter((r) => r.matches_brand).length : 0;
    const placed = def + news;
    if (placed === 0) {
      const prevPlaced = prevByKw.has(kw.keyword) ? prevByKw.get(kw.keyword)! : null;
      const drop = prevPlaced !== null ? Math.max(0, prevPlaced - placed) : 0;
      critical.push({
        keyword: kw.keyword,
        placedCount: placed,
        placedCountPrev: prevPlaced,
        drop,
      });
    }
  }

  // 14-day 未达理想序列（按日历日聚合 → 14 个 bucket）
  // Sparkline 的 points 是 number[]（不接受 null），所以缺失天用 0 占位 ——
  // 跟"那天 0 个未达理想"语义会混，但在 hero 这种纯趋势卡片里可接受。
  const heroBuckets = bucketByCalendarDay([...hist].reverse(), 14);
  const sparkPoints = heroBuckets.map((b) =>
    b.record ? _missingForMetric(b.record.metric, idealN) : 0,
  );
  // 5 个等间距日历日 label —— 从聚合后的 14 天 bucket 中按等间距抽取，
  // 跟 points 的视觉位置对齐（之前是独立日历公式，跟 points 维度不匹配）。
  const sparkAxis = (() => {
    const count = 5;
    const out: string[] = [];
    if (heroBuckets.length === 0) return out;
    for (let i = 0; i < count; i++) {
      const idx = Math.round((i / (count - 1)) * (heroBuckets.length - 1));
      out.push(heroBuckets[Math.min(idx, heroBuckets.length - 1)].label);
    }
    return out;
  })();

  return {
    taskId: task.id,
    taskName: task.name,
    missingCurrent,
    missingPrev,
    missingDelta: missingPrev !== null ? missingCurrent - missingPrev : 0,
    critical,
    sparkPoints,
    sparkAxis,
  };
}

const baiduAlerts = computed<BaiduAlertHero[]>(() => {
  const out: BaiduAlertHero[] = [];
  for (const t of tasks.value) {
    const hero = _buildBaiduAlertHero(t);
    if (hero) out.push(hero);
  }
  return out;
});

const baiduAlertIdx = ref(0);
watch(baiduAlerts, (next) => {
  if (baiduAlertIdx.value >= next.length) baiduAlertIdx.value = 0;
});
const currentBaiduAlert = computed<BaiduAlertHero | null>(() =>
  baiduAlerts.value[baiduAlertIdx.value] ?? null,
);

function cycleBaiduAlert(dir: -1 | 1): void {
  const n = baiduAlerts.value.length;
  if (n <= 1) return;
  baiduAlertIdx.value = (baiduAlertIdx.value + dir + n) % n;
}

// AlertDetailModal 开关 + 当前喂给 modal 的 data
const baiduAlertModalOpen = ref(false);
function openBaiduAlertModal(): void {
  if (!currentBaiduAlert.value) return;
  baiduAlertModalOpen.value = true;
}

function taskOverallStatus(task: TaskItem): { statusLabel: string; tone: PillTone } {
  const hist = taskHistories.value[task.id] ?? [];
  const latest = hist[0];
  if (!latest) return { statusLabel: "未跑", tone: "info" };
  if (latest.status === "captcha") return { statusLabel: "验证码", tone: "warn" };
  if (latest.status === "failed" || latest.status === "error") {
    return { statusLabel: "失败", tone: "alert" };
  }
  const idealN = (task.config as any)?.ideal_rank ?? 5;
  const total = latest.metric?.keywords?.length ?? 0;
  if (total === 0) return { statusLabel: "未跑", tone: "info" };
  const idealCount = _idealCountForMetric(latest.metric, idealN);
  const missingRate = 1 - idealCount / total;
  // 与 hero 触发同阈：未达理想 > 60% → 预警
  if (missingRate > 0.6) return { statusLabel: "预警", tone: "alert" };
  return { statusLabel: "正常", tone: "ok" };
}

const latestResult = computed(() =>
  history.value.length > 0 ? history.value[0] : null,
);

const latestMetric = computed<BaiduMetric | null>(
  () => latestResult.value?.metric ?? null,
);

const prevMetric = computed<BaiduMetric | null>(
  () => (history.value.length > 1 ? history.value[1]?.metric ?? null : null),
);

// 关键词渲染源——以 config.search_keywords 为基准（93 行始终不变），
// 用 latestMetric.keywords 按 keyword 名 dict 查找填充每行结果。
// 这样检测中途（latestMetric 已存在但只含部分 keyword）也能正常显示
// "未跑/已检"占位，而不是只渲染已检完的几个。
// 修复 bug: 详情页只显示 1 条关键词，等检测完才显示 93 条。
const keywordRows = computed(() => {
  const base = (selectedTask.value?.config as any)?.search_keywords as string[] | undefined;
  if (!base || base.length === 0) return [];
  const map = new Map(
    (latestMetric.value?.keywords ?? []).map((k) => [k.keyword, k]),
  );
  return base.map((name) => ({
    keyword: name,
    result: map.get(name) ?? null,
  }));
});

// Trend chart: history is newest-first from API; reverse for chronological
const chronoHistory = computed(() => [...history.value].reverse());

// Sparkline: matched_keywords over last 14 results (kept for potential future use)
const _sparkPoints = computed<number[]>(() =>
  chronoHistory.value
    .slice(-14)
    .map((r) => r.metric?.matched_keywords ?? 0),
);
void _sparkPoints; // suppress unused warning

// Level 2 任务汇总卡的 14 天日历窗口 —— 跟 Level 1 同套聚合逻辑。
const levelTwoCalendarBuckets = computed(() =>
  bucketByCalendarDay(chronoHistory.value, 14),
);

// 5 个等间距日历日 label，从 14 天 bucket 中等距抽取 —— Sparkline 的 axis-labels
// 跟 points 长度可以不一致（Sparkline 文档明确允许），所以这里仍然给 5 条
// 视觉锚点，避免 14 条 MM-DD 挤在一起。
const sparkLabels = computed<string[]>(() => {
  const all = levelTwoCalendarBuckets.value;
  if (all.length === 0) return [];
  const count = 5;
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const idx = Math.round((i / (count - 1)) * (all.length - 1));
    out.push(all[Math.min(idx, all.length - 1)].label);
  }
  return out;
});

// Get ideal_rank from selected task config (default 5)
const idealRank = computed<number>(() => {
  const v = (selectedTask.value?.config as any)?.ideal_rank;
  return typeof v === 'number' && v > 0 ? v : 5;
});

// 本次卡位数量: how many keywords have default_first_rank within ideal_rank
const placedCountCurrent = computed<number>(() => {
  if (!latestMetric.value) return 0;
  return latestMetric.value.keywords.filter(
    (kw) => kw.default_first_rank > 0 && kw.default_first_rank <= idealRank.value,
  ).length;
});
void placedCountCurrent; // suppress unused warning

const placedCountPrev = computed<number>(() => {
  if (!prevMetric.value) return 0;
  return prevMetric.value.keywords.filter(
    (kw) => kw.default_first_rank > 0 && kw.default_first_rank <= idealRank.value,
  ).length;
});
void placedCountPrev; // suppress unused warning

// Sparkline: 卡位 count (not matched_keywords) over last 14 days
// 按本地日历日聚合 —— 同一天多次跑取最后一次，缺失天用 0 占位（Sparkline
// 的 points: number[] 不接受 null）。跟 sparkLabels 的 14 天 bucket 对齐。
const sparkPointsPlaced = computed<number[]>(() =>
  levelTwoCalendarBuckets.value.map((b) => {
    if (!b.record?.metric) return 0;
    return b.record.metric.keywords.filter(
      (kw) => kw.default_first_rank > 0 && kw.default_first_rank <= idealRank.value,
    ).length;
  }),
);

// Currently selected keyword's details for the right panel detail section
// selectedKeywordIdx 现在指向 keywordRows（合并源）的索引——未跑的关键词
// row.result 是 null，KPI 卡也跟着显示 0/选择关键词，跟原"未选中"语义一致。
const currentKeyword = computed<BaiduPerKeyword | null>(() => {
  if (selectedKeywordIdx.value === null) return null;
  const row = keywordRows.value[selectedKeywordIdx.value];
  return row?.result ?? null;
});

/**
 * Name of currently selected keyword. Resolves to either:
 *   - latestMetric.keywords[idx].keyword when we have real data, or
 *   - selectedTask.config.search_keywords[idx] when in the fallback path
 *     (no history yet — the left list shows config-only rows).
 * Used by runNow() to scope the «启动监测» dispatch to one keyword.
 */
const currentKeywordName = computed<string | null>(() => {
  if (selectedKeywordIdx.value === null) return null;
  if (currentKeyword.value) return currentKeyword.value.keyword;
  const fallback = selectedTask.value?.config?.search_keywords ?? [];
  return fallback[selectedKeywordIdx.value] ?? null;
});

// Delta: total_default_matches between current and previous
// (kept for potential future use; not rendered in current template)
const _matchesDelta = computed<number | null>(() => {
  const cur = latestMetric.value?.total_default_matches ?? null;
  const prv = prevMetric.value?.total_default_matches ?? null;
  if (cur === null || prv === null) return null;
  return cur - prv;
});
void _matchesDelta; // suppress unused warning

// ──────────────────────────── helpers ────────────────────────────

type PillTone = "ok" | "warn" | "alert" | "info";

// taskRowState (last-status driven Level 1 pill) removed in favor of
// taskOverallStatus, which derives «正常 / 警报» from the 70% 理想率 rule
// the user spec'd. scheduleLabel removed too — Level 1 no longer surfaces
// 检查频率/上次检查; users set schedule via the 定时监测 button.

/** First keyword label with "(+N)" if more exist. (kept for future use) */
function _keywordSummary(cfg: TaskItem["config"]): string {
  const kws = cfg.search_keywords ?? [];
  if (kws.length === 0) return "—";
  const first = kws[0];
  if (kws.length === 1) return first;
  return `${first} (+${kws.length - 1})`;
}
void _keywordSummary; // suppress unused warning

// ──────────────────────────── data loading ────────────────────────────

async function loadTasks() {
  loadingTasks.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: "baidu_keyword" },
    });
    tasks.value = r.data.tasks ?? [];
    // Default Level 1 preview = first task
    if (tasks.value.length > 0 && previewId.value === null) {
      previewId.value = tasks.value[0].id;
    }
    // Kick off parallel per-task history loads —— needed for the Level 1
    // 状态 column (理想率) and the right-card 14-day sparkline. We don't
    // await; let them stream in. Each completion updates taskHistories
    // and Vue reactivity refreshes the affected cells.
    void loadAllTaskHistories();
    // Do NOT auto-select for drill-down: Level 1 is the default landing.
  } catch (e: any) {
    toast.error(`加载任务列表失败: ${e?.message ?? e}`);
  } finally {
    loadingTasks.value = false;
  }
}

/** Fan out per-task /results?limit=14 calls in parallel. */
async function loadAllTaskHistories(): Promise<void> {
  const ids = tasks.value.map((t) => t.id);
  await Promise.all(ids.map((id) => loadTaskHistory(id)));
}

async function loadTaskHistory(taskId: number): Promise<void> {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 14 },
    });
    taskHistories.value = {
      ...taskHistories.value,
      [taskId]: r.data.results ?? [],
    };
  } catch (e) {
    // Per-task failures shouldn't kill the whole Level 1 view ——
    // surface as empty history (→ 状态 shows 未跑).
    taskHistories.value = { ...taskHistories.value, [taskId]: [] };
  }
}

async function loadHistory(id: number) {
  loadingHistory.value = true;
  history.value = [];
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: id, limit: 30 },
    });
    history.value = r.data.results ?? [];
  } catch (e: any) {
    toast.error(`加载历史记录失败: ${e?.message ?? e}`);
  } finally {
    loadingHistory.value = false;
  }
}

/**
 * Level 2 «启动监测» —— only fires the currently selected keyword's SERP,
 * not the entire task. Backend merges the partial result into the previous
 * snapshot so other keywords' data is preserved.
 */
async function runNow() {
  if (!selectedId.value || runningNow.value) return;
  // 必须先在左栏选中一个关键词
  const kw = currentKeywordName.value;
  if (!kw) {
    toast.warn("请先在左侧选中一个关键词");
    return;
  }
  runningNow.value = true;
  markRunning(selectedId.value);
  try {
    await whenReady();
    await sidecar.client.post(
      `/api/monitor/tasks/${selectedId.value}/run-now`,
      null,
      { params: { keyword: kw } },
    );
    toast.info(`已派发「${kw}」，结果会通过 SSE 流推回`);
  } catch (e: any) {
    if (selectedId.value !== null) clearRunning(selectedId.value);
    toast.error(`派发失败: ${e?.message ?? e}`);
  } finally {
    runningNow.value = false;
  }
}

/**
 * Level 1 «立刻监测» —— runs the entire task (all keywords). Different
 * intent from Level 2 button: from the list we don't know which keyword
 * the user cares about, so we sweep all.
 */
async function runNowTask(id: number) {
  if (runningNow.value) return;
  markRunning(id);
  try {
    await whenReady();
    await sidecar.client.post(`/api/monitor/tasks/${id}/run-now`);
    toast.info("已派发，结果会通过 SSE 流推回");
  } catch (e: any) {
    clearRunning(id);
    toast.error(`派发失败: ${e?.message ?? e}`);
  }
}

/**
 * Cooperative cancel —— ask sidecar to abort the in-flight fetch at the
 * next checkpoint. We don't optimistically clear runningTaskIds here:
 * the SSE `failed` event (with reason "cancelled by user") will arrive
 * within a second or two and the store updates from there. That way
 * the UI is honest about "stopping… now stopped" instead of flipping
 * back to play before the worker actually exits.
 */
async function cancelTask(taskId: number) {
  try {
    const delivered = await monitorStatus.cancel(taskId);
    if (delivered) {
      toast.info("已请求停止，等待当前关键词完成后中断…");
    } else {
      toast.warn("没有可停止的任务（可能已经结束）");
    }
  } catch (e: any) {
    toast.error(`停止失败: ${e?.message ?? e}`);
  }
}

async function deleteTask(task: TaskItem) {
  // 不要用浏览器原生 confirm() —— 在 Tauri 2 WebView2 里
  // 走 dialog.confirm 插件，未授权的 capabilities 会抛
  // 「dialog.confirm not allowed. Command not found」。
  // 项目里通用 confirmDialog 是纯 Vue 模态，无 Tauri 依赖。
  if (!(await confirmDialog(
    `确认删除任务「${task.name}」？此操作不可恢复。`,
    { title: "删除监测任务" },
  ))) return;
  try {
    await whenReady();
    await sidecar.client.delete(`/api/monitor/tasks/${task.id}`);
    toast.success("已删除");
    if (selectedId.value === task.id) selectedId.value = null;
    await loadTasks();
  } catch (e: any) {
    toast.error(`删除失败: ${e?.message ?? e}`);
  }
}

function openEdit(task: TaskItem) {
  emit("edit-task", task);
}

/**
 * 导出 preview task 的所有关键词卡位情况为 CSV。
 * 列：关键词名字 | 卡位数量（默认搜索 + 最新资讯如有）。
 * 数据来源：该任务最近一份 result。无历史时给出 toast 提示。
 */
function exportPreviewCsv(): void {
  const t = previewTask.value;
  if (!t) {
    toast.warn("没有选中的任务");
    return;
  }
  const hist = taskHistories.value[t.id] ?? [];
  const latest = hist[0];
  if (!latest || !latest.metric || !Array.isArray(latest.metric.keywords)) {
    toast.warn("该任务还没有可导出的监测结果，请先运行一次监测");
    return;
  }
  const rows: string[] = ["关键词名字,卡位数量"];
  for (const kw of latest.metric.keywords) {
    const def = Number(kw.default_matched_count) || 0;
    const news = kw.news_present
      ? kw.news_results.filter((r) => r.matches_brand).length
      : 0;
    const total = def + news;
    // CSV-escape quotes + comma in keyword text
    const safeName = `"${(kw.keyword || "").replace(/"/g, '""')}"`;
    rows.push(`${safeName},${total}`);
  }
  // 加 BOM 让 Excel 正确识别 UTF-8
  const blob = new Blob(["﻿" + rows.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `${t.name}-卡位-${ts}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast.success(`已导出 ${latest.metric.keywords.length} 条关键词`);
}

/** 「定时监测」按钮 —— 复用编辑模态，让用户在里面调 schedule_cron。 */
function openScheduleEditor(): void {
  const t = previewTask.value;
  if (!t) {
    toast.warn("没有选中的任务");
    return;
  }
  emit("edit-task", t);
}

function backToList(): void {
  selectedId.value = null;
  selectedKeywordIdx.value = null;
}

// ──────────────────────────── risk_control resume ────────────────────────────

const resuming = ref(false);

async function resumeTask(): Promise<void> {
  if (!selectedTask.value?.id || resuming.value) return;
  resuming.value = true;
  try {
    await whenReady();
    await sidecar.client.post(`/api/monitor/tasks/${selectedTask.value.id}/resume`);
    toast.success("已派发续抓任务，从断点继续");
    await loadHistory(selectedTask.value.id);
    await loadTaskHistory(selectedTask.value.id);
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`续抓失败：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  } finally {
    resuming.value = false;
  }
}

// ──────────────────────────── lifecycle ────────────────────────────

// ──────────────────────────── SSE bus ────────────────────────────
// Listen to monitor events so the row shows 「监测中…」 spinner while a
// task is actually fetching, and clears + reloads history on finish.

let stopSse: (() => void) | null = null;

function startSse(): void {
  // The monitorStatus store owns the canonical SSE subscription that
  // maintains running/progress state. This component-level subscription
  // only handles page-specific reactions (history reload + last_status
  // mutation on the local tasks list).
  stopSse = subscribe("/api/monitor/events", {
    finished: (d: any) => {
      if (typeof d.task_id !== "number") return;
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) {
        t.last_check_at = d.at ?? t.last_check_at;
        t.last_status = d.result?.status ?? t.last_status;
      }
      // Always refresh Level 1 history slot so 状态 + sparkline catch up
      void loadTaskHistory(d.task_id);
      // If it's the selected task, reload Level 2 history too.
      if (selectedId.value === d.task_id) {
        loadHistory(d.task_id);
      }
    },
    failed: (d: any) => {
      if (typeof d.task_id !== "number") return;
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) t.last_status = "failed";
    },
  });
}

onMounted(() => {
  loadTasks();
  startSse();
  // Force a /running hydrate as belt-and-suspenders for the
  // "navigate away → come back" case. The store also polls every 30 s,
  // but mount-time hydrate eliminates the visible delay.
  void monitorStatus.hydrate();
});

onUnmounted(() => {
  if (stopSse) stopSse();
  stopSse = null;
});

watch(selectedId, (id) => {
  if (id !== null) loadHistory(id);
});

// Auto-select first keyword when entering Level 2 (works for both
// metric.keywords data AND the fallback config.search_keywords path).
watch(() => latestMetric.value?.keywords, (kws) => {
  if (kws && kws.length > 0 && selectedKeywordIdx.value === null) {
    selectedKeywordIdx.value = 0;
  }
});
watch(() => selectedTask.value?.config?.search_keywords, (kws) => {
  if (kws && kws.length > 0 && selectedKeywordIdx.value === null) {
    selectedKeywordIdx.value = 0;
  }
}, { immediate: true });

// Parent (MonitorView) calls this after a create/update from the shared
// AddTaskModal so the new task shows up immediately without tab-switching.
defineExpose({ reload: loadTasks });
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">

    <!-- ═══════════════════════════════════════════════════════════
         LEVEL 1: 默认落地页 —— selectedId === null
         两卡并列：左=任务表，右=占位提示
    ════════════════════════════════════════════════════════════════ -->
    <template v-if="selectedId === null">

      <!--
        紧急告警 hero —— 完全对齐 MonitorView 的知乎/评论告警 hero：
        padding 26/28、双 blur blob、28px 双行主标题、橙底「起一篇救场」
        按钮。三种告警卡片的高度和视觉层级现在统一。
        触发：任务状态 = 警报（理想率 < 70%）。多条命中时可翻页。
      -->
      <div
        v-if="currentBaiduAlert"
        class="relative overflow-hidden flex-shrink-0"
        :style="{
          background: 'var(--dark)',
          color: '#fbf7ec',
          borderRadius: 'var(--radius-card)',
          padding: '26px 28px',
        }"
      >
        <div
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: '-50px', left: '20px',
            width: '240px', height: '240px',
            background: 'radial-gradient(circle, rgba(216,90,72,0.5), transparent 65%)',
            filter: 'blur(12px)',
            pointerEvents: 'none',
          }"
        />
        <div
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: '60px', left: '400px',
            width: '220px', height: '220px',
            background: 'radial-gradient(circle, rgba(238,106,42,0.4), transparent 65%)',
            filter: 'blur(12px)',
            pointerEvents: 'none',
          }"
        />
        <div class="relative flex items-center justify-between gap-6">
          <div class="min-w-0">
            <div
              class="flex items-center gap-2 text-[11px] uppercase"
              :style="{ letterSpacing: '1.5px', color: 'rgba(255,255,255,0.5)' }"
            >
              <span>{{ baiduAlerts.length }} 个紧急告警</span>
              <span
                v-if="baiduAlerts.length > 1"
                :style="{ color: 'rgba(255,255,255,0.4)', letterSpacing: '0' }"
              >· {{ baiduAlertIdx + 1 }} / {{ baiduAlerts.length }}</span>
            </div>
            <div
              class="font-display mt-2 font-bold"
              :style="{ fontSize: '28px', letterSpacing: '-0.5px', lineHeight: '1.25' }"
            >
              「{{ currentBaiduAlert.taskName }}」<br />
              <span :style="{ color: 'var(--primary)' }">{{ currentBaiduAlert.missingCurrent }} 个关键词未达理想卡位</span>
            </div>
            <div class="mt-2 text-[12.5px]" :style="{ color: 'rgba(255,255,255,0.6)' }">
              <template v-if="currentBaiduAlert.missingPrev !== null">
                上次未达 {{ currentBaiduAlert.missingPrev }} 条 · 变化
                <span
                  :style="{
                    color: currentBaiduAlert.missingDelta > 0
                      ? 'var(--red, #d85a48)'
                      : currentBaiduAlert.missingDelta < 0
                        ? 'var(--green, #6c9b5d)'
                        : 'rgba(255,255,255,0.6)',
                  }"
                >{{ currentBaiduAlert.missingDelta > 0 ? '+' : '' }}{{ currentBaiduAlert.missingDelta }}</span>
              </template>
              <template v-else>首次抓取</template>
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <!-- 翻页箭头 (only when 2+ alerts) -->
            <template v-if="baiduAlerts.length > 1">
              <button
                type="button"
                title="上一条告警"
                class="inline-flex items-center justify-center"
                :style="{
                  width: '32px',
                  height: '32px',
                  borderRadius: '999px',
                  background: 'rgba(255,255,255,0.08)',
                  color: '#fbf7ec',
                  border: '1px solid rgba(255,255,255,0.12)',
                }"
                @click="cycleBaiduAlert(-1)"
              >
                <Icon name="arrowLeft" :size="14" />
              </button>
              <button
                type="button"
                title="下一条告警"
                class="inline-flex items-center justify-center"
                :style="{
                  width: '32px',
                  height: '32px',
                  borderRadius: '999px',
                  background: 'rgba(255,255,255,0.08)',
                  color: '#fbf7ec',
                  border: '1px solid rgba(255,255,255,0.12)',
                }"
                @click="cycleBaiduAlert(1)"
              >
                <Icon name="arrowRight" :size="14" />
              </button>
              <span :style="{ width: '6px' }" />
            </template>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium"
              :style="{
                background: 'rgba(255,255,255,0.08)',
                color: '#fbf7ec',
                borderRadius: '999px',
                border: '1px solid rgba(255,255,255,0.12)',
              }"
              @click="openBaiduAlertModal()"
            >
              <Icon name="fileText" :size="14" />
              <span>查看报告</span>
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium"
              :style="{
                background: 'var(--primary)',
                color: '#fff',
                borderRadius: '999px',
              }"
              @click="router.push({ name: 'article' })"
            >
              <Icon name="edit" :size="14" />
              <span>新建文章补救</span>
            </button>
          </div>
        </div>
      </div>

      <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">

        <!-- ── 左卡：监测任务表 ───────────────────────────────── -->
        <section
          class="flex min-h-0 flex-col"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <!-- Card header -->
          <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="font-display text-[14px] font-semibold">监测任务</div>
              <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                任务列表
              </div>
            </div>
            <div class="flex flex-shrink-0 gap-2">
              <button
                type="button"
                class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px]"
                :style="{
                  background: 'transparent',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '999px',
                }"
                @click="emit('batch-import')"
              >
                <Icon name="folder" :size="12" />
                <span>批量导入</span>
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
                :style="{
                  background: 'var(--primary-deep)',
                  color: '#fff',
                  borderRadius: '999px',
                }"
                @click="emit('add-task')"
              >
                <Icon name="plus" :size="12" />
                <span>新增任务</span>
              </button>
            </div>
          </div>

          <!-- Table: fills remaining height -->
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <!--
              Header row —— 4 列均匀分布的视觉权重：任务名最宽（1.6fr），
              变化/状态/操作各占接近的 ~0.85fr，让 3 个非主列读起来等高
              均衡；操作列 header 居中以对齐下方按钮组。
            -->
            <div
              class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
              :style="{
                gridTemplateColumns: '1.6fr .85fr .85fr 1fr',
                letterSpacing: '1.2px',
                color: 'var(--ink-3)',
                borderBottom: '1px solid var(--line)',
              }"
            >
              <div>任务名字</div>
              <div>变化</div>
              <div class="text-center">状态</div>
              <div class="text-center">操作</div>
            </div>

            <!-- Loading state -->
            <div
              v-if="loadingTasks"
              class="py-10 text-center text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              加载中…
            </div>

            <!-- Empty state -->
            <div
              v-else-if="tasks.length === 0"
              class="flex flex-1 flex-col items-center justify-center gap-1 py-16"
            >
              <div class="text-[13px] font-medium" :style="{ color: 'var(--ink-2)' }">暂无百度排名任务</div>
              <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                点击右上「+ 新增任务」开始监测
              </div>
            </div>

            <!-- Task rows -->
            <template v-else>
              <div
                v-for="(t, i) in tasks"
                :key="t.id"
                class="grid cursor-pointer items-center transition"
                :style="{
                  gridTemplateColumns: '1.6fr .85fr .85fr 1fr',
                  background: previewId === t.id ? 'var(--card-2)' : 'transparent',
                  borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
                  padding: '14px 8px',
                  borderRadius: '10px',
                }"
                @mouseenter="(e) => { previewId = t.id; (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                @mouseleave="(e) => { if (previewId !== t.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
                @click="previewId = t.id"
              >
                <!--
                  任务名字 + N关键词·品牌
                  任务名字本身是「点击进 Level 2」的热区；整行点击只是
                  把右卡预览定位到这条任务（previewId）。
                -->
                <div class="min-w-0">
                  <button
                    type="button"
                    class="truncate text-[13px] font-medium text-left w-full"
                    :style="{ color: 'var(--primary-deep)', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }"
                    @click.stop="selectedId = t.id"
                  >{{ t.name }}</button>
                  <div
                    class="truncate text-[11px] mt-0.5"
                    :style="{ color: 'var(--ink-3)' }"
                  >
                    {{ t.config.search_keywords?.length ?? 0 }} 个关键词
                    <template v-if="t.config.target_brand">
                      · 品牌 {{ t.config.target_brand }}
                    </template>
                  </div>
                </div>

                <!-- 变化：无历史，一律"—" -->
                <div :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>

                <!--
                  状态：跑动中显示「N / M」+ 进度条；空闲时显示 70% 理想率 pill。
                  进度条 = 当前完成的关键词数 / 总关键词数；居中对齐 column。
                -->
                <div class="flex flex-col items-center gap-1">
                  <template v-if="isRunning(t.id)">
                    <div class="text-[11.5px] font-medium" :style="{ color: 'var(--primary-deep)' }">
                      {{ taskProgress[t.id]?.current ?? 0 }} / {{ taskProgress[t.id]?.total ?? (t.config.search_keywords?.length ?? 0) }}
                    </div>
                    <!-- Thin orange progress bar; width = current/total% -->
                    <div
                      :style="{
                        width: '80%',
                        height: '4px',
                        background: 'var(--card-2)',
                        borderRadius: '999px',
                        overflow: 'hidden',
                      }"
                    >
                      <div
                        :style="{
                          height: '100%',
                          width: (taskProgress[t.id]?.total
                            ? Math.min(100, Math.round((taskProgress[t.id]!.current / Math.max(1, taskProgress[t.id]!.total)) * 100))
                            : 0) + '%',
                          background: 'var(--primary-deep)',
                          transition: 'width 0.3s ease',
                        }"
                      />
                    </div>
                  </template>
                  <Pill v-else :tone="taskOverallStatus(t).tone">{{ taskOverallStatus(t).statusLabel }}</Pill>
                </div>

                <!--
                  操作 cell —— justify-center 与 header「操作」居中对齐；
                  ▶ 立刻监测 / ✎ 编辑 / 🗑 删除 三个图标按钮。
                  跑动中：play 图标变 ⏹ stop，点击调 store.cancel() 协作
                  停止后端的 SERP 循环；后端会在下一个关键词边界 raise
                  _CancelledFetch → SSE failed → store 清状态 → 按钮回到
                  play 形态。
                -->
                <div class="flex items-center justify-center gap-1">
                  <button
                    v-if="isRunning(t.id)"
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--red, #d85a48)',
                      cursor: 'pointer',
                    }"
                    title="停止监测"
                    @click.stop="cancelTask(t.id)"
                  >
                    <Icon name="x" :size="13" />
                  </button>
                  <button
                    v-else
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--primary-deep)',
                      cursor: 'pointer',
                    }"
                    title="立刻监测"
                    @click.stop="runNowTask(t.id)"
                  >
                    <Icon name="play" :size="13" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{ borderRadius: '999px', color: 'var(--ink-3)' }"
                    title="编辑任务"
                    @click.stop="openEdit(t)"
                  >
                    <Icon name="edit" :size="13" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{ borderRadius: '999px', color: 'var(--ink-3)' }"
                    title="删除任务"
                    @click.stop="deleteTask(t)"
                  >
                    <Icon name="trash" :size="13" />
                  </button>
                </div>
              </div>
            </template>
          </div>
        </section>

        <!-- ── 右卡：任务详情（含底部 导出/定时 按钮） ───────────── -->
        <section
          class="flex min-h-0 flex-col"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <!-- 没有任务时：占位 -->
          <div
            v-if="!previewTask"
            class="flex flex-1 flex-col items-center justify-center text-center"
            :style="{ color: 'var(--ink-3)' }"
          >
            <div class="text-[14px] font-medium mb-1">暂无任务</div>
            <div class="text-[11.5px]">点击左上「+ 新增任务」开始监测</div>
          </div>

          <!-- 有任务：属性预览 -->
          <template v-else>
            <!-- 标题：previewTask 的名字 -->
            <div class="mb-3 flex-shrink-0">
              <div class="font-display text-[14px] font-semibold">{{ previewTask.name }}</div>
              <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                任务详情
              </div>
            </div>

            <!-- 属性表 (滚动区) -->
            <div class="flex flex-col gap-3 flex-1 min-h-0 overflow-y-auto">
              <!-- 目标品牌 -->
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">目标品牌</div>
                <div class="text-[13px] font-medium">{{ previewTask.config.target_brand || '—' }}</div>
              </div>

              <!--
                14 天关键词趋势 —— 满足理想卡位的关键词数量随时间变化。
                复用历史报告的 LineChart（chart.js v4，平滑张力 0.25，
                带 x/y 轴 + 鼠标 hover tooltip），比纯 SVG sparkline 更丝滑。
                数据点 < 2 时给文字占位（chart.js 单点会画不出曲线）。
              -->
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">最近 14 天关键词趋势</div>
                <LineChart
                  v-if="previewSparkPoints.length >= 2"
                  :labels="previewChartLabels"
                  :series="previewChartSeries"
                />
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
                  无历史数据 —— 跑几次「立刻监测」后会成线。
                </div>
              </div>
              <!-- 搜索关键词列表已按需求移除 —— 关键词通过 Level 2 查看。 -->
            </div>

            <!-- 底部按钮：导出数据 / 定时监测 (pinned at bottom of right card) -->
            <div class="pt-4 flex-shrink-0 flex gap-2">
              <button
                type="button"
                class="flex-1 text-[12.5px] font-medium"
                :style="{
                  padding: '9px 14px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  color: 'var(--ink-2)',
                  cursor: 'pointer',
                }"
                @click="exportPreviewCsv()"
              >导出数据</button>
              <button
                type="button"
                class="flex-1 text-[12.5px] font-medium"
                :style="{
                  padding: '9px 14px',
                  background: 'var(--primary-deep)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                }"
                @click="openScheduleEditor()"
              >定时监测</button>
            </div>
          </template>
        </section>

      </div>
    </template>

    <!-- ═══════════════════════════════════════════════════════════
         LEVEL 2: drill-down —— selectedId !== null
         顶部返回 + 任务信息 + 双卡（关键词列表 + 任务汇总）
    ════════════════════════════════════════════════════════════════ -->
    <template v-else>

      <!-- 双卡 -->
      <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">

        <!-- ── 左卡：关键词列表 ──────────────────────────────── -->
        <section
          class="flex min-h-0 flex-col"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <!-- Card header with back button INSIDE (B站 style — 简洁版) -->
          <div class="mb-3 flex-shrink-0 flex items-start gap-3">
            <button
              type="button"
              class="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center"
              :style="{
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
                color: 'var(--ink-2)',
                cursor: 'pointer',
              }"
              title="返回任务列表"
              @click="backToList()"
            >
              <Icon name="arrowLeft" :size="14" />
            </button>
            <div class="min-w-0 flex-1">
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                百度排名 · 关键词列表
              </div>
              <div class="font-display text-[14px] font-semibold mt-0.5">
                {{ selectedTask?.name ?? '' }}
              </div>
            </div>
            <!-- 右上角徽章：N 个关键词（仿 B 站「5 条」） -->
            <div
              class="flex-shrink-0 text-[11px] px-2.5 py-1"
              :style="{
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
                color: 'var(--ink-3)',
              }"
            >
              {{ selectedTask?.config?.search_keywords?.length ?? 0 }} 个关键词
            </div>
          </div>

          <!-- Table -->
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <!-- Loading -->
            <div
              v-if="loadingHistory"
              class="py-10 text-center text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              加载中…
            </div>

            <!-- 关键词表：单一渲染源 keywordRows，以 config.search_keywords 为基准的 93 行，
                 按 keyword 名从 latestMetric.keywords 查结果填充；未匹配的渲染「未跑」。 -->
            <!-- Header row -->
            <div
              class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
              :style="{
                gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
                letterSpacing: '1.2px',
                color: 'var(--ink-3)',
                borderBottom: '1px solid var(--line)',
              }"
            >
              <div>关键词</div>
              <div>默认卡位</div>
              <div>资讯卡位</div>
              <div>状态</div>
            </div>

            <!-- Empty state -->
            <div
              v-if="keywordRows.length === 0"
              class="py-10 text-center text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              此任务未配置搜索关键词
            </div>

            <!-- Keyword rows -->
            <div
              v-for="(row, i) in keywordRows"
              :key="row.keyword + '-' + i"
              class="grid items-center cursor-pointer transition"
              :style="{
                gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
                borderBottom: i < keywordRows.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '12px 8px',
                background: selectedKeywordIdx === i ? 'var(--card-2)' : 'transparent',
              }"
              @click="selectedKeywordIdx = i"
              @mouseenter="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
              @mouseleave="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
            >
              <!-- 关键词 -->
              <div class="min-w-0">
                <div
                  class="truncate text-[12.5px] font-medium"
                  :style="{ color: 'var(--ink)' }"
                >{{ row.keyword }}</div>
              </div>

              <!-- 默认卡位 -->
              <div>
                <template v-if="row.result">
                  <div
                    class="font-display text-[13px] font-bold"
                    :style="{ color: row.result.default_matched_count > 0 ? 'var(--primary-deep)' : 'var(--ink-3)' }"
                  >
                    {{ row.result.default_matched_count }}
                  </div>
                </template>
                <div v-else :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
              </div>

              <!-- 资讯卡位 -->
              <div>
                <template v-if="row.result && row.result.news_present">
                  <div
                    class="font-display text-[13px] font-bold"
                    :style="{ color: row.result.news_results.filter(r => r.matches_brand).length > 0 ? '#4f7cff' : 'var(--ink-3)' }"
                  >
                    {{ row.result.news_results.filter(r => r.matches_brand).length }}
                  </div>
                </template>
                <div v-else-if="row.result && !row.result.news_present" class="font-display text-[13px] font-bold" :style="{ color: 'var(--ink-3)' }">无</div>
                <div v-else :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
              </div>

              <!--
                状态 ＝ 是否达到任务设置的「理想卡位（数量）」。
                总卡位 ＝ 默认搜索命中 ＋ 最新资讯命中（无资讯块时只算默认）。
                ≥ idealRank → 理想，否则 → 未理想；抓取失败单独标记；未跑（row.result === null）显示「未跑」。
              -->
              <div>
                <template v-if="!row.result">
                  <Pill tone="info">未跑</Pill>
                </template>
                <template v-else-if="row.result.fetch_error">
                  <Pill tone="alert">抓取失败</Pill>
                </template>
                <template v-else>
                  <Pill
                    :tone="(row.result.default_matched_count + (row.result.news_present ? row.result.news_results.filter(r => r.matches_brand).length : 0)) >= idealRank ? 'ok' : 'warn'"
                  >{{ (row.result.default_matched_count + (row.result.news_present ? row.result.news_results.filter(r => r.matches_brand).length : 0)) >= idealRank ? '理想' : '未理想' }}</Pill>
                </template>
              </div>
            </div>
          </div>
        </section>

        <!-- ── 右卡：任务汇总 ─────────────────────────────────── -->
        <section
          class="flex min-h-0 flex-col overflow-y-auto"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <!-- Card header -->
          <div class="mb-3 flex-shrink-0">
            <div class="font-display text-[14px] font-semibold">任务汇总</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              全部关键词的命中趋势 + 排名详情
            </div>
          </div>

          <!-- 风控 banner：上次抓取被风控拦截时展示 -->
          <div
            v-if="selectedTask && selectedTask.last_status === 'risk_control'"
            class="mb-3 flex-shrink-0 rounded p-3 text-[12.5px]"
            :style="{
              background: 'var(--primary-soft)',
              border: '1px solid var(--primary)',
              color: 'var(--primary-deep)',
            }"
          >
            <div :style="{ fontWeight: 600, marginBottom: '4px' }">
              ⚠ 上次抓取被风控拦截
            </div>
            <div :style="{ color: 'var(--ink-3)', fontSize: '11px', marginBottom: '8px' }">
              百度风控机制阻断了本次扫描，从断点续抓可继续之前进度
            </div>
            <Btn
              variant="solid"
              small
              :disabled="resuming"
              @click="resumeTask"
            >
              {{ resuming ? '续抓中…' : '从断点续抓' }}
            </Btn>
          </div>

          <!-- Loading -->
          <div
            v-if="loadingHistory"
            class="py-6 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            加载中…
          </div>

          <!-- KPI 二联：默认搜索卡位 / 最新资讯卡位 -->
          <div class="mb-4 grid flex-shrink-0 grid-cols-2 gap-3">
            <!-- KPI 1: 默认搜索卡位 = 自家在默认搜索的命中总数 -->
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">默认搜索卡位</div>
              <div class="font-display text-[20px] font-bold">{{ currentKeyword ? currentKeyword.default_matched_count : 0 }}</div>
              <div class="text-[10.5px] mt-1" :style="{ color: 'var(--ink-3)' }">
                <template v-if="currentKeyword">关键词：{{ currentKeyword.keyword }}</template>
                <template v-else>选择左侧关键词查看</template>
              </div>
            </div>

            <!-- KPI 2: 最新资讯卡位 = 自家在最新资讯的命中总数；无资讯块时显示「无」 -->
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">最新资讯卡位</div>
              <div class="font-display text-[20px] font-bold">
                <template v-if="!currentKeyword">0</template>
                <template v-else-if="!currentKeyword.news_present">无</template>
                <template v-else>{{ currentKeyword.news_results.filter(r => r.matches_brand).length }}</template>
              </div>
              <div class="text-[10.5px] mt-1" :style="{ color: 'var(--ink-3)' }">
                <template v-if="!currentKeyword || !currentKeyword.news_present">该关键词无最新资讯</template>
                <template v-else>资讯区命中</template>
              </div>
            </div>
          </div>

          <!-- Sparkline: 卡位数量 最近 14 天 -->
          <div class="mb-4 flex-shrink-0">
            <div class="text-[12.5px] font-semibold mb-2">最近 14 天关键词卡位趋势</div>
            <Sparkline
              v-if="sparkPointsPlaced.filter(v => v > 0).length > 1"
              :points="sparkPointsPlaced"
              :width="380"
              :height="70"
              stroke="var(--primary, #ee6a2a)"
              :axis-labels="sparkLabels"
              fluid
            />
            <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
              无历史数据 —— 跑几次「启动监测」后会成线。
            </div>
          </div>

          <!-- 选中关键词排名详情 -->
          <div class="flex-1 min-h-0 overflow-y-auto">
            <div class="text-[12.5px] font-semibold mb-2 flex items-baseline justify-between">
              <span>排名情况</span>
              <span v-if="currentKeyword" class="text-[11px] font-normal" :style="{ color: 'var(--ink-3)' }">
                关键词：{{ currentKeyword.keyword }}
              </span>
            </div>

            <div v-if="!currentKeyword" class="text-center text-[12px] py-8" :style="{ color: 'var(--ink-3)' }">
              点击左侧关键词查看排名详情
            </div>

            <template v-else>
              <!-- 抓取错误 -->
              <div
                v-if="currentKeyword.fetch_error"
                class="text-[11.5px] mb-3 px-3 py-2 rounded"
                :style="{ background: 'rgba(239, 68, 68, 0.08)', color: '#b91c1c', borderLeft: '3px solid #b91c1c' }"
              >
                抓取失败：{{ currentKeyword.fetch_error.slice(0, 120) }}
              </div>

              <!-- 默认搜索排名 -->
              <div
                class="mb-3 rounded"
                :style="{ background: 'var(--card-2)', borderLeft: '3px solid var(--primary)', padding: '10px 12px' }"
              >
                <div class="text-[12px] font-semibold mb-2">默认搜索排名</div>
                <div v-if="currentKeyword.default_results.length === 0" class="text-[11px] py-2" :style="{ color: 'var(--ink-3)' }">
                  无默认搜索结果
                </div>
                <div v-else class="flex flex-col gap-1">
                  <a
                    v-for="r in currentKeyword.default_results"
                    :key="r.url"
                    :href="r.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-[11.5px] py-1.5 px-2 rounded block transition-opacity hover:opacity-80"
                    :style="{
                      background: r.matches_brand ? 'rgba(238, 106, 42, 0.10)' : 'transparent',
                      border: r.matches_brand ? '1px solid rgba(238, 106, 42, 0.3)' : 'none',
                      textDecoration: 'none',
                      color: 'inherit',
                    }"
                  >
                    <div class="flex items-baseline gap-2">
                      <span class="font-display font-bold flex-shrink-0" :style="{ color: r.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)' }">
                        #{{ r.rank }}
                      </span>
                      <span class="truncate flex-1">{{ r.title || '(无标题)' }}</span>
                      <span v-if="r.matches_brand" class="text-[10.5px] font-medium px-1.5 py-0.5 rounded flex-shrink-0" :style="{ background: 'var(--primary-deep)', color: '#fff' }">
                        自家
                      </span>
                    </div>
                  </a>
                </div>
              </div>

              <!-- 最新资讯排名 (only if news_present) -->
              <div
                v-if="currentKeyword.news_present"
                class="mb-3 rounded"
                :style="{ background: 'rgba(79, 124, 255, 0.06)', borderLeft: '3px solid #4f7cff', padding: '10px 12px' }"
              >
                <div class="text-[12px] font-semibold mb-2">最新资讯排名</div>
                <div class="flex flex-col gap-1">
                  <a
                    v-for="r in currentKeyword.news_results"
                    :key="r.url"
                    :href="r.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-[11.5px] py-1.5 px-2 rounded block transition-opacity hover:opacity-80"
                    :style="{
                      background: r.matches_brand ? 'rgba(79, 124, 255, 0.12)' : 'transparent',
                      border: r.matches_brand ? '1px solid rgba(79, 124, 255, 0.3)' : 'none',
                      textDecoration: 'none',
                      color: 'inherit',
                    }"
                  >
                    <div class="flex items-baseline gap-2">
                      <span class="font-display font-bold flex-shrink-0" :style="{ color: r.matches_brand ? '#4f7cff' : 'var(--ink-2)' }">
                        #{{ r.rank }}
                      </span>
                      <span class="truncate flex-1">{{ r.title || '(无标题)' }}</span>
                      <span v-if="r.matches_brand" class="text-[10.5px] font-medium px-1.5 py-0.5 rounded flex-shrink-0" :style="{ background: '#4f7cff', color: '#fff' }">
                        自家
                      </span>
                    </div>
                  </a>
                </div>
              </div>
            </template>
          </div>

          <!-- 底部：启动监测 -->
          <div class="mt-5 flex-shrink-0">
            <button
              type="button"
              class="w-full font-medium text-[14px]"
              :disabled="isRunning(selectedId!)"
              :style="{
                padding: '12px 24px',
                borderRadius: '10px',
                background: isRunning(selectedId!) ? 'var(--card-2)' : 'var(--primary-deep)',
                color: isRunning(selectedId!) ? 'var(--ink-3)' : '#fff',
                cursor: isRunning(selectedId!) ? 'not-allowed' : 'pointer',
                border: 'none',
                transition: 'background .15s',
              }"
              @click="runNow()"
            >
              {{ isRunning(selectedId!) ? '监测中…' : '▶ 启动监测' }}
            </button>
          </div>
        </section>

      </div>
    </template>

    <!-- 紧急告警详情 modal — 复用 AlertDetailModal 的 baidu_alert 分支 -->
    <AlertDetailModal
      v-if="currentBaiduAlert"
      v-model:open="baiduAlertModalOpen"
      kind="baidu_alert"
      :baidu-data="{
        title: `「${currentBaiduAlert.taskName}」百度卡位告警`,
        subtitle: `${currentBaiduAlert.missingCurrent} 个关键词未达理想卡位`,
        missingCurrent: currentBaiduAlert.missingCurrent,
        missingPrev: currentBaiduAlert.missingPrev,
        missingDelta: currentBaiduAlert.missingDelta,
        sparkPoints: currentBaiduAlert.sparkPoints,
        sparkAxis: currentBaiduAlert.sparkAxis,
        critical: currentBaiduAlert.critical,
      }"
    />

  </div>
</template>
