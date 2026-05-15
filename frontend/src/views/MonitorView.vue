<script setup lang="ts">
/**
 * 监测中心 — V1 design alignment.
 *
 * 三大 tab：知乎问题 / 平台评论 / 历史报告。顶部使用 V1 同款的圆角胶囊
 * pivot（黑底高亮 + 计数徽章），下方根据 tab 渲染 dark 告警 hero +
 * 主表格 + 详情面板 / 平台子 pivot / 报告列表。
 *
 * 数据流保持原貌：
 *   /api/monitor/tasks?type=...        → 任务列表
 *   /api/monitor/results?task_id=X     → 任务历史（sparkline）
 *   /api/monitor/cookies?platform=...  → cookie 池（按钮入口）
 *   /api/monitor/tasks/{id}/run-now    → 强制立刻派发
 *   /api/monitor/events SSE            → 实时刷新
 *
 * sidecar 没启动 / 表里没数据时，沿用 ArticleView 的演示模式：把 V1
 * 设计稿里的 mock 任务 / 抢占者 / 留存趋势铺出来，让用户
 * 一眼看到这页能呈现什么。演示行不挂"立刻跑/删除"按钮（id 是负数标记，
 * 不应该误调真实接口）。
 *
 * Cookie + 新增任务按钮按用户要求收进左侧任务卡的标题行右侧，避免和
 * 顶部 pivot 抢视线。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import AddTaskModal from "@/components/monitor/AddTaskModal.vue";
import AlertDetailModal from "@/components/monitor/AlertDetailModal.vue";
import BatchImportTaskModal from "@/components/monitor/BatchImportTaskModal.vue";
import CookieManagerModal from "@/components/monitor/CookieManagerModal.vue";
import EditBatchModal from "@/components/monitor/EditBatchModal.vue";
import RetentionPage from "@/components/monitor/history/RetentionPage.vue";
import ZhihuRankingPage from "@/components/monitor/history/ZhihuRankingPage.vue";
import BaiduRankingPage from "@/components/monitor/history/BaiduRankingPage.vue";
import BaiduSEOAnalytics from "@/components/monitor/history/BaiduSEOAnalytics.vue";

import { subscribe } from "@/api/client";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const sidecar = useSidecar();
const cfg = useConfig();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const { whenReady } = useSidecarReady();

type Tab = "zhihu" | "comment" | "baidu" | "report";
type CommentPlatform = "bilibili" | "douyin" | "kuaishou";

function tabFromQuery(): Tab {
  const q = route.query.tab;
  if (q === "zhihu" || q === "comment" || q === "baidu" || q === "report") return q;
  return "zhihu";
}
const activeTab = ref<Tab>(tabFromQuery());
watch(
  () => route.query.tab,
  () => {
    activeTab.value = tabFromQuery();
  },
);

const PLATFORM_TYPE: Record<CommentPlatform, string> = {
  bilibili: "bilibili_comment",
  douyin: "douyin_comment",
  kuaishou: "kuaishou_comment",
};
const commentSubtab = ref<CommentPlatform>("bilibili");

type HistorySubtab = "retention" | "zhihu" | "baidu";
const historySubtab = ref<HistorySubtab>("retention");

interface Task {
  id: number;
  type: string;
  name: string;
  target_url: string;
  enabled: boolean;
  schedule_cron: string;
  last_check_at: string | null;
  last_status: string | null;
}
const tasks = ref<Task[]>([]);
const selectedTaskId = ref<number | null>(null);
const taskResults = ref<Array<{ checked_at: string; status: string; rank: number; metric: any }>>([]);

const loading = ref(false);
const failed = ref(false);

// ── Sample fallbacks (V1 设计稿) ────────────────────────────────────────
interface SampleZhihu {
  id: string;
  kw: string;
  type: string;
  lastRank: number | null;
  prevRank: number;
  lastCheck: string;
  status: "ok" | "warn" | "alert";
  delta: number;
  /** 知乎问题原 URL，详情卡的「问题链接」按钮跳到这里。 */
  targetUrl: string;
}
// V1 设计稿示例数据，发布前清空保留空状态 —— 首次启动监测中心应显示
// 「暂无监测任务」而不是假的产品/排名/抢占者数据。
const SAMPLE_ZHIHU: SampleZhihu[] = [];

const SAMPLE_TOP3: Array<{ who: string; title: string; rank: number }> = [];

const SAMPLE_SPARK_RANK: number[] = [];

interface SampleComment {
  id: string;
  kw: string;
  lastChecked: string;
  retained: number;
  total: number;
  delta: number;
  status: "ok" | "warn" | "alert";
}
// V1 设计稿示例数据，发布前清空保留空状态 —— 三个平台默认全空，
// SAMPLE_COMMENTS[platform].length === 0 时模板会渲染"还没有监测任务"。
const SAMPLE_COMMENTS: Record<CommentPlatform, SampleComment[]> = {
  bilibili: [],
  douyin: [],
  kuaishou: [],
};

const SAMPLE_RETENTION: number[] = [];

// 评论 tab 的三级导航数据结构：任务 → 视频列表 → 单视频详情。
// 一级（SAMPLE_COMMENTS）：任务名 / 留存 / 变化 / 状态
// 二级（这里 SAMPLE_VIDEOS）：每个任务下挂的视频列表
// 三级（视频本身）：自己在该视频下的评论原文 + 排名 + 状态 + URL
//
// 一二级同时可见 —— 左列在一级显任务列表，二级换成视频列表（保留返回箭头）；
// 三级走右列，把汇总图换成单视频详情。这样一屏就能看完上下文，不需要 modal。
interface VideoEntry {
  id: string;
  url: string;
  /** 视频原标题 —— 列表渲染时只取前 15 字，鼠标悬停看全文。 */
  title: string;
  /** 我自己在这条视频下的评论原文。 */
  myComment: string;
  /** 我的评论目前在该视频下的热度排名。 */
  rank: number;
  /** 评论现状：在显 / 被删 / 折叠。 */
  status: "ok" | "deleted" | "folded";
  /** 评论发出时间。 */
  postedAt: string;
  /** 视频评论区的总评论数（仅展示用）。 */
  totalComments: number;
}
// V1 设计稿示例数据，发布前清空保留空状态 —— 任务列表为空时下面这些
// 视频明细自然进不到，发布版本里全部清掉。
const SAMPLE_VIDEOS: Record<string, VideoEntry[]> = {};

function truncate15(s: string): string {
  return s.length > 15 ? `${s.slice(0, 15)}…` : s;
}

// Sparkline 横轴日期 —— 用今天往回推 N 天，演示模式下纯前端生成。
function daysAgoLabels(count: number, totalSpan: number): string[] {
  // count: 想显示几个标签；totalSpan: 数据覆盖多少天
  const out: string[] = [];
  const now = new Date();
  for (let i = 0; i < count; i++) {
    const offset = Math.round(((count - 1 - i) / (count - 1)) * (totalSpan - 1));
    const d = new Date(now.getTime() - offset * 24 * 60 * 60 * 1000);
    out.push(`${d.getMonth() + 1}/${d.getDate()}`);
  }
  return out;
}
const ZHIHU_SPARK_LABELS = daysAgoLabels(5, 14); // 14 次快照横跨 14 天
const COMMENT_SPARK_LABELS = daysAgoLabels(7, 7); // 7 天留存

// 监测启停 + 频率 —— 演示模式下保存在本地 ref 里，真实模式改 PATCH
// /api/monitor/tasks/{id}。每个任务一份独立设置，切任务不会丢状态。
interface MonitorState {
  enabled: boolean;
  schedule: string;
}
const SCHEDULE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "manual", label: "手动触发" },
  { value: "hourly-1", label: "每 1 小时" },
  { value: "hourly-6", label: "每 6 小时" },
  { value: "daily-09:00", label: "每天 09:00" },
  { value: "daily-12:00", label: "每天 12:00" },
  { value: "daily-18:00", label: "每天 18:00" },
];
function scheduleLabel(v: string): string {
  return SCHEDULE_OPTIONS.find((o) => o.value === v)?.label ?? v;
}
// 初始默认 enabled=false：第一眼看到的是橙色 CTA「启动监测」，邀请用户
// 主动点一下确认开启；点完才翻到灰色「监测进行中」状态。这是用户明确
// 要求的交互方向 —— 不要一进来就显示一个已勾选的 disabled-looking 按钮。
const zhihuMonitorState = ref<Record<string, MonitorState>>({
  "s-z1": { enabled: false, schedule: "hourly-6" },
  "s-z2": { enabled: false, schedule: "daily-09:00" },
  "s-z3": { enabled: false, schedule: "hourly-6" },
  "s-z4": { enabled: false, schedule: "manual" },
  "s-z5": { enabled: false, schedule: "daily-09:00" },
  "s-z6": { enabled: false, schedule: "daily-09:00" },
});
const commentMonitorState = ref<Record<string, MonitorState>>({
  "s-b1": { enabled: false, schedule: "hourly-1" },
  "s-b2": { enabled: false, schedule: "hourly-6" },
  "s-b3": { enabled: false, schedule: "daily-09:00" },
});

function ensureZhihuState(id: string): MonitorState {
  if (!zhihuMonitorState.value[id]) {
    zhihuMonitorState.value[id] = { enabled: false, schedule: "daily-09:00" };
  }
  return zhihuMonitorState.value[id];
}
function ensureCommentState(id: string): MonitorState {
  if (!commentMonitorState.value[id]) {
    commentMonitorState.value[id] = { enabled: false, schedule: "daily-09:00" };
  }
  return commentMonitorState.value[id];
}
function toggleMonitor(scope: "zhihu" | "comment", id: string) {
  const st = scope === "zhihu" ? ensureZhihuState(id) : ensureCommentState(id);
  st.enabled = !st.enabled;
  toast.info(`已${st.enabled ? "启动" : "暂停"}监测`);
}
function changeSchedule(scope: "zhihu" | "comment", id: string, v: string) {
  const st = scope === "zhihu" ? ensureZhihuState(id) : ensureCommentState(id);
  st.schedule = v;
  toast.success(`监测频率：${scheduleLabel(v)}`);
}

// V1 设计稿示例数据，发布前清空保留空状态。
const SAMPLE_DELETED: Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }> = [];

// 平台 chip 计数清零 —— V1 设计稿示例任务已清空，发布前保留空状态。
const PLATFORMS: Array<{ k: CommentPlatform; l: string; color: string; count: number }> = [
  { k: "bilibili", l: "B 站", color: "#ee6a2a", count: 0 },
  { k: "douyin", l: "抖音", color: "#1e1c19", count: 0 },
  { k: "kuaishou", l: "快手", color: "#f5c042", count: 0 },
];

// ── Demo mode: sidecar 不可用或表为空 ──────────────────────────────────
const demoMode = computed(() => failed.value || (!loading.value && tasks.value.length === 0));

// ── Loaders ─────────────────────────────────────────────────────────────
async function loadTasks(typeKey: string) {
  loading.value = true;
  failed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: typeKey },
    });
    tasks.value = r.data.tasks ?? [];
    if (tasks.value.length > 0 && (!selectedTaskId.value || !tasks.value.find((t) => t.id === selectedTaskId.value))) {
      selectedTaskId.value = tasks.value[0].id;
    }
  } catch (e: any) {
    failed.value = true;
    tasks.value = [];
    if (e?.response?.status !== 503) {
      toast.error(`加载失败：${e?.message ?? e}`);
    }
  } finally {
    loading.value = false;
  }
}

async function loadResults(taskId: number) {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 14 },
    });
    taskResults.value = r.data.results ?? [];
  } catch {
    taskResults.value = [];
  }
}

// ── Comment snapshots（每个 task 最近两次 result）─────────────────────
//
// 评论 tab 的 rich UI（留存 8/14 / 变化 -3 / 被删评论列表 / 留存趋势 sparkline）
// 全靠后端 MonitorResult.metric 里塞的 `matched / hot_comments / total_fetched`
// 字段（见 csm_core/monitor/platforms/_comment_common.py）。`/api/monitor/tasks`
// 只回任务元信息，要拿 metric 必须二次拉 `/api/monitor/results?task_id=X`。
//
// 这里在 loadTasks 后并行 fetch 每条任务的近两次 result：latest 算
// "当前留存"，prev 算"变化 delta"（matched_now - matched_prev）。limit=2
// 一次请求双带，比 limit=1 + limit=1 多一次 round trip 划算。
//
// 历史 30 条用于父批次的 7 天 sparkline —— 但 30 条 × N 任务太重，分两
// 跳：L1/L2 列表用 limit=2 的轻量结果；进 L3 单视频详情时再单独 fetch
// limit=14（沿用 zhihu 的 loadResults 路径）。
interface TaskSnapshot {
  matched: boolean;
  rank: number;
  /** 评论：用户填的"理想排名上限"。知乎：用户填的 top_n（前几条答案要扫描） */
  alert_top_n: number;
  /** 评论后台实际扫描范围（默认 150）。rank=-1 时区分"丢失"vs"无" */
  scrape_top_n: number;
  /** 评论：本次实际比对了多少条 hot 评论；知乎不用 */
  scope_total: number;
  hot_comments: Array<{ author?: string; text?: string; rank?: number; nickname?: string }>;
  total_fetched: number;
  my_comment_text: string;
  checked_at: string;
  status: string;
  /** 知乎专用：前 top_n 条答案里命中目标品牌的条数 */
  matched_count: number;
  /** 知乎专用：所有命中位置（1-based） */
  matched_ranks: number[];
  /** 知乎专用：用户的目标品牌关键词（详情卡 / 抢占者高亮要用） */
  target_brand: string;
}
interface TaskSnapshotPair {
  latest: TaskSnapshot | null;
  prev: TaskSnapshot | null;
}
const taskSnapshots = ref<Record<number, TaskSnapshotPair>>({});

function _resultToSnapshot(r: any): TaskSnapshot | null {
  if (!r) return null;
  const m = r.metric ?? {};
  // alert_top_n 优先 metric.alert_top_n（评论新后端）/ metric.top_n（知乎 +
  // 旧评论 result）；再缺给个 5 兜底
  const alertTopN =
    typeof m.alert_top_n === "number" ? m.alert_top_n
    : typeof m.top_n === "number" ? m.top_n
    : 5;
  const scrapeTopN = typeof m.scrape_top_n === "number" ? m.scrape_top_n : 150;
  const scopeTotal =
    typeof m.scope_total === "number" ? m.scope_total
    : Array.isArray(m.hot_comments) ? m.hot_comments.length
    : 0;
  // matched_count / matched_ranks：知乎新后端字段；旧 result（无 matched_count）
  // 用 rank > 0 兜底成 1，rank=-1 兜底成 0（单命中假设，避免 NaN）。
  const rankVal = typeof r.rank === "number" ? r.rank : -1;
  const matchedCount =
    typeof m.matched_count === "number" ? m.matched_count
    : rankVal > 0 ? 1 : 0;
  const matchedRanks =
    Array.isArray(m.matched_ranks) ? m.matched_ranks.filter((x: any) => typeof x === "number")
    : rankVal > 0 ? [rankVal] : [];
  return {
    matched: Boolean(m.matched) || matchedCount > 0,
    rank: rankVal,
    alert_top_n: alertTopN,
    scrape_top_n: scrapeTopN,
    scope_total: scopeTotal,
    hot_comments: Array.isArray(m.hot_comments) ? m.hot_comments : [],
    total_fetched: typeof m.total_fetched === "number" ? m.total_fetched : 0,
    my_comment_text: typeof m.my_comment_text === "string" ? m.my_comment_text : "",
    checked_at: r.checked_at ?? "",
    status: r.status ?? "",
    matched_count: matchedCount,
    matched_ranks: matchedRanks,
    target_brand: typeof m.target_brand === "string" ? m.target_brand : "",
  };
}

async function _fetchSnapshotPair(taskId: number): Promise<void> {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 2 },
    });
    const rows: any[] = r.data?.results ?? [];
    // 后端按 checked_at desc 返回，rows[0] = latest, rows[1] = prev
    taskSnapshots.value = {
      ...taskSnapshots.value,
      [taskId]: {
        latest: _resultToSnapshot(rows[0] ?? null),
        prev: _resultToSnapshot(rows[1] ?? null),
      },
    };
  } catch {
    // 静默失败 —— 没拿到 snapshot 的 task 在 UI 上显示 "—" 即可，
    // 不弹 toast（一次点开就 N 个错误会刷屏）。
  }
}

async function loadTaskSnapshots() {
  // 评论 / 知乎 tab 都用：L1 行的"上次 / 变化 / 留存"列要靠 latest+prev
  // 两次 result 计算。空表跳过。
  if (!tasks.value.length) return;
  await Promise.all(tasks.value.map((t) => _fetchSnapshotPair(t.id)));
}

// 原子加载平台任务 + snapshots：把新平台 tasks 与每条 task 的近两条 result
// snapshot 全部静默拉到临时对象，最后一次性赋给 reactive state。早期实现
// 在 watch 里先 ``taskSnapshots.value = {}`` 同步清空再 ``await loadTasks``，
// 期间旧 tasks 拿不到 snapshot 会全部回落到 ``matched=false / rank=-1`` 渲
// 染（视觉上是「整列瞬间变成无 / 未找到」的明显闪动），切平台、切顶级
// tab 都触发。原子赋值后中间态被消除，UI 直接从旧终态跳到新终态。
async function loadTasksAndSnapshotsAtomic(typeKey: string): Promise<void> {
  loading.value = true;
  failed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: typeKey } });
    const newTasks: Task[] = r.data?.tasks ?? [];
    const pairs: Record<number, TaskSnapshotPair> = {};
    await Promise.all(newTasks.map(async (t) => {
      try {
        const rr = await sidecar.client.get("/api/monitor/results", {
          params: { task_id: t.id, limit: 2 },
        });
        const rows: any[] = rr.data?.results ?? [];
        pairs[t.id] = {
          latest: _resultToSnapshot(rows[0] ?? null),
          prev: _resultToSnapshot(rows[1] ?? null),
        };
      } catch {
        // 单任务 snapshot 失败保持空 pair，让 UI 对该行显示 "—"，
        // 不阻塞整批切换。
      }
    }));
    tasks.value = newTasks;
    taskSnapshots.value = pairs;
    if (newTasks.length > 0 && (!selectedTaskId.value || !newTasks.find((t) => t.id === selectedTaskId.value))) {
      selectedTaskId.value = newTasks[0].id;
    }
  } catch (e: any) {
    failed.value = true;
    tasks.value = [];
    taskSnapshots.value = {};
    if (e?.response?.status !== 503) toast.error(`加载失败：${e?.message ?? e}`);
  } finally {
    loading.value = false;
  }
}

const showAddTask = ref(false);
const showBatchImport = ref(false);
// 编辑模式：非空时 AddTaskModal 走 PATCH 路径，关闭后清掉
const editingTask = ref<Task | null>(null);
// 评论批次编辑/删除
const showEditBatch = ref(false);
const editingBatchName = ref("");
const editingBatchTasks = ref<Task[]>([]);
function openEditTask(t: Task) {
  editingTask.value = t;
  showAddTask.value = true;
}
function clearEditOnClose() {
  // AddTaskModal 关闭后回到"新增"语义；不清掉的话下次点新增按钮会带
  // 残留任务进编辑模式。
  if (!showAddTask.value) editingTask.value = null;
}

// Modal 回调 —— 不放 inline `Promise.all(...)` 在模板里：Vue 编译内联
// 箭头函数时把 `Promise.all` 解析路径出错，运行时报
// "Cannot read properties of undefined (reading 'all')"。抽到这里
// setup 作用域里 `Promise` 是确定的全局引用。
async function onTaskMutatedReload() {
  const typeKey = activeTab.value === "zhihu" ? "zhihu_question" : PLATFORM_TYPE[commentSubtab.value];
  await loadTasks(typeKey);
  await loadTaskSnapshots();
}

// 评论批次：根据 batchName 拢到子 task 列表，打开编辑 modal
function openEditBatch(batchName: string) {
  editingBatchName.value = batchName;
  editingBatchTasks.value = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  showEditBatch.value = true;
}

// 批量删除：并行 DELETE 所有子 task，全部失败也只弹一条 toast
async function deleteBatch(batchName: string) {
  const childIds = tasks.value
    .filter((t) => parseBatchName(t.name) === batchName)
    .map((t) => t.id);
  if (!childIds.length) return;
  if (!(await confirmDialog(
    `删除批次「${batchName}」下的 ${childIds.length} 条任务？历史结果会一并删除。`,
    { title: "删除批次" },
  ))) return;
  const failures: string[] = [];
  await Promise.all(
    childIds.map((id) =>
      sidecar.client
        .delete(`/api/monitor/tasks/${id}`)
        .catch((e: any) => {
          const detail = e?.response?.data?.detail ?? e?.message ?? e;
          failures.push(`#${id}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
        }),
    ),
  );
  if (!failures.length) {
    toast.success(`已删除 ${childIds.length} 条任务`);
  } else {
    toast.warn(`完成 ${childIds.length - failures.length} / ${childIds.length}，失败 ${failures.length}`);
    console.warn("[batch delete failures]", failures);
  }
  // 刷新任务列表 + 快照；若用户当前停在被删的批次上，回到 L1
  if (selectedCommentTaskId.value === batchName) {
    selectedCommentTaskId.value = null;
    selectedVideoId.value = null;
  }
  await loadTasks(PLATFORM_TYPE[commentSubtab.value]);
  await loadTaskSnapshots();
}
const showCookieMgr = ref(false);

// 紧急告警详情 modal —— 两种语义共用一张面板。模态本身不
// 抓数据，全部由 MonitorView 在打开时算好塞进 alertDetail。
const showAlertModal = ref(false);
const alertKind = ref<"zhihu_alert" | "comment_alert">("zhihu_alert");

// 告警详情 modal 用的真实数据（zhihu / comment 两套），openZhihuAlert /
// openCommentAlert 时同步算好。Null = 没数据，模态展示空态。
interface AlertTimelineItem {
  t: string;       // 时间显示
  rank: string;    // "#3" / "—"
  text: string;
  level: "alert" | "warn" | "info";
}
interface AlertGrabber {
  rank: number;
  who: string;
  title: string;
  voteup?: number;
  matchesBrand?: boolean;  // 是不是自家（高亮用）
}
interface ZhihuAlertData {
  title: string;
  subtitle: string;
  matchedCount: number;       // 本次命中数
  matchedCountPrev: number | null;  // 上次命中数；null = 无历史
  alertTopN: number;
  firstRank: number;          // 首条命中位置；-1 表示无命中
  scheduleLabel: string;
  sparkPoints: number[];      // 历次首条命中排名（无则 0）
  sparkAxis: string[];
  timeline: AlertTimelineItem[];
  topAnswers: AlertGrabber[];
}
interface AlertDeletedComment {
  who: string;       // 抢占者作者（hot_comments[0].author）或 "—"
  text: string;      // 我的评论原文
  date: string;
  state: "被删" | "折叠";
}
interface CommentAlertData {
  title: string;
  subtitle: string;
  retained: number;
  total: number;
  ratio: number;     // 0-100
  recentDelta: number;   // 留存数变化
  prevRetained: number | null;
  sparkPoints: number[];
  sparkAxis: string[];
  deleted: AlertDeletedComment[];
}
const zhihuAlertData = ref<ZhihuAlertData | null>(null);
const commentAlertData = ref<CommentAlertData | null>(null);

// 紧急告警 hero 改成可翻页的卡片堆叠：多条告警同时存在时，hero 只显示
// 当前一条 + 后面 2 张更小更暗的「卡片影子」，左右两个圆形 chevron 切上
// 一条 / 下一条。1 条告警时影子和 chevron 自动隐藏（hasNav 为 false）。
interface HeroAlert {
  keyword: string;
  headline: string;
  subtitle: string;
  /** 知乎告警：定位到具体 task。模态拉这个 task 的 results 14 条来画
   *  排名 sparkline / 时间线 / 抢占者。 */
  taskId?: number;
  /** 评论告警：定位到具体批次。模态聚合本批次内所有子 task 的 snapshot。 */
  batchName?: string;
}
// zhihuAlerts / commentAlerts 在文件后段（unifiers 区块之后）声明 ——
// 它们是 computed，依赖 tasks/taskSnapshots/realCommentRows，那些都得
// 先定义。这里只放索引和切换 helper；computed 本体见下方"Real-data
// unifiers"段。computed body 是惰性的，模板渲染 / 用户点击时才求值，
// 所以这里 forward reference 不会触发 TDZ。
const zhihuAlertIdx = ref(0);
const commentAlertIdx = ref(0);
const currentZhihuAlert = computed(() => zhihuAlerts.value[zhihuAlertIdx.value]);
const currentCommentAlert = computed(() => commentAlerts.value[commentAlertIdx.value]);
function cycleAlert(kind: "zhihu" | "comment", dir: 1 | -1) {
  const list = (kind === "zhihu" ? zhihuAlerts : commentAlerts).value;
  const ref_ = kind === "zhihu" ? zhihuAlertIdx : commentAlertIdx;
  if (!list.length) return;
  // wrap-around 让用户在 1↔️N 来回切不会被卡住；按钮始终可点，更直白。
  ref_.value = (ref_.value + dir + list.length) % list.length;
}

function _formatTimelineTime(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now);
  yest.setDate(yest.getDate() - 1);
  const isYesterday = d.toDateString() === yest.toDateString();
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (sameDay) return `今天 ${hhmm}`;
  if (isYesterday) return `昨天 ${hhmm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hhmm}`;
}

async function _buildZhihuAlertData(taskId: number, alert: HeroAlert): Promise<ZhihuAlertData | null> {
  const t = tasks.value.find((x) => x.id === taskId);
  if (!t) return null;
  // 拉近 14 条 result 做 sparkline + 时间线 + 取最新的 metric.answers
  let history: any[] = [];
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 14 },
    });
    history = r.data?.results ?? [];
  } catch {
    history = [];
  }
  const latest = history[0];
  const prev = history[1];
  const latestMatchedCount =
    typeof latest?.metric?.matched_count === "number"
      ? latest.metric.matched_count
      : (latest?.rank ?? -1) > 0 ? 1 : 0;
  const prevMatchedCount =
    prev
      ? (typeof prev?.metric?.matched_count === "number"
          ? prev.metric.matched_count
          : (prev?.rank ?? -1) > 0 ? 1 : 0)
      : null;
  const alertTopN =
    typeof latest?.metric?.top_n === "number"
      ? latest.metric.top_n
      : Number((t.schedule_cron && undefined) ?? 10) || 10;
  // sparkline 点：每次首条命中位置；-1 显示成 alertTopN+5 哨兵让 sparkline
  // 视觉上能区分"上榜"vs"掉出"。倒序排成"老 → 新"。
  const sparkPoints = history
    .slice()
    .reverse()
    .map((r: any) => {
      const rank = r?.rank ?? -1;
      return rank > 0 ? rank : alertTopN + 5;
    });
  // sparkline X 轴：取首尾 + 3 个等距日期标签
  const sparkAxis: string[] = [];
  if (history.length >= 2) {
    const first = new Date(history[history.length - 1].checked_at);
    const last = new Date(history[0].checked_at);
    const span = last.getTime() - first.getTime();
    for (let i = 0; i < 5; i++) {
      const d = new Date(first.getTime() + (span * i) / 4);
      sparkAxis.push(`${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    }
  }
  // 时间线：最多取 5 条最近的 result
  const timeline: AlertTimelineItem[] = history.slice(0, 5).map((r: any, i: number) => {
    const rank = r?.rank ?? -1;
    const mc =
      typeof r?.metric?.matched_count === "number"
        ? r.metric.matched_count
        : rank > 0 ? 1 : 0;
    const prevR = history[i + 1];
    const prevRank = prevR?.rank ?? null;
    let text: string;
    let level: AlertTimelineItem["level"];
    if (rank === -1) {
      text = `「${t.name}」掉出前 ${alertTopN}`;
      level = "alert";
    } else if (prevRank && prevRank > 0 && rank > prevRank) {
      text = `下滑至第 ${rank} 名（−${rank - prevRank}）`;
      level = "warn";
    } else if (prevRank && prevRank > 0 && rank < prevRank) {
      text = `升至第 ${rank} 名（+${prevRank - rank}）· 命中 ${mc} 条`;
      level = "info";
    } else {
      text = `第 ${rank} 名（持平）· 命中 ${mc} 条`;
      level = "info";
    }
    return {
      t: _formatTimelineTime(r.checked_at),
      rank: rank > 0 ? `#${rank}` : "—",
      text,
      level,
    };
  });
  // Top 抢占者：latest.metric.answers[:3]，命中目标品牌的高亮
  const answers = Array.isArray(latest?.metric?.answers) ? latest.metric.answers : [];
  const topAnswers: AlertGrabber[] = answers.slice(0, 3).map((a: any) => ({
    rank: Number(a.rank) || 0,
    who: String(a.author || "—"),
    title: String(a.content_preview || ""),
    voteup: Number(a.voteup_count) || 0,
    matchesBrand: Boolean(a.matches_brand),
  }));
  return {
    title: `「${t.name}」紧急告警`,
    subtitle: `知乎问题 · ${alert.subtitle}`,
    matchedCount: latestMatchedCount,
    matchedCountPrev: prevMatchedCount,
    alertTopN,
    firstRank: latest?.rank ?? -1,
    scheduleLabel: t.schedule_cron === "manual" ? "手动" : t.schedule_cron,
    sparkPoints,
    sparkAxis,
    timeline,
    topAnswers,
  };
}

function _buildCommentAlertData(batchName: string, alert: HeroAlert): CommentAlertData | null {
  const childTasks = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  if (!childTasks.length) return null;
  let retained = 0;
  let prevRetained = 0;
  let havePrev = false;
  const deleted: AlertDeletedComment[] = [];
  for (const t of childTasks) {
    const pair = taskSnapshots.value[t.id];
    const snap = pair?.latest;
    const prev = pair?.prev;
    if (snap?.matched) retained++;
    if (prev) {
      havePrev = true;
      if (prev.matched) prevRetained++;
    }
    if (snap && !snap.matched) {
      const top1 = snap.hot_comments?.[0];
      const grabber = (top1 as any)?.author || (top1 as any)?.nickname || "—";
      deleted.push({
        who: `@${grabber}`,
        text: snap.my_comment_text || "（无原文）",
        date: snap.checked_at ? new Date(snap.checked_at).toLocaleDateString() : "—",
        state: snap.rank > 0 ? "折叠" : "被删",
      });
    }
  }
  const total = childTasks.length;
  const ratio = total > 0 ? Math.round((retained / total) * 100) : 0;
  // sparkline：暂时只两点（latest / prev 留存率）；若无 prev 单点 fallback
  const sparkPoints: number[] = [];
  if (havePrev) {
    sparkPoints.push(Math.round((prevRetained / total) * 100));
  }
  sparkPoints.push(ratio);
  const platformLabel =
    childTasks[0].type === "bilibili_comment" ? "B 站"
    : childTasks[0].type === "douyin_comment" ? "抖音"
    : childTasks[0].type === "kuaishou_comment" ? "快手" : "评论";
  return {
    title: `「${batchName}」评论留存告警`,
    subtitle: `${platformLabel} · ${alert.subtitle}`,
    retained,
    total,
    ratio,
    recentDelta: havePrev ? retained - prevRetained : 0,
    prevRetained: havePrev ? prevRetained : null,
    sparkPoints,
    sparkAxis: [], // 两点没必要画轴
    deleted,
  };
}

async function openZhihuAlert(alert?: HeroAlert) {
  alertKind.value = "zhihu_alert";
  commentAlertData.value = null;
  zhihuAlertData.value = null;
  showAlertModal.value = true;
  // 用 currentZhihuAlert 兜底（没显式传时）
  const a = alert ?? currentZhihuAlert.value;
  if (a?.taskId) {
    zhihuAlertData.value = await _buildZhihuAlertData(a.taskId, a);
  }
}
function openCommentAlert(alert?: HeroAlert) {
  alertKind.value = "comment_alert";
  zhihuAlertData.value = null;
  commentAlertData.value = null;
  showAlertModal.value = true;
  const a = alert ?? currentCommentAlert.value;
  if (a?.batchName) {
    commentAlertData.value = _buildCommentAlertData(a.batchName, a);
  }
}
function onAlertAction(a: "rescue" | "repost" | "close") {
  showAlertModal.value = false;
  if (a === "rescue") {
    router.push({ name: "article" });
  } else if (a === "repost") {
    // 真实告警接入后由后端给出推荐补发文案；空示例阶段给出一句通用占位。
    const sample = "在此处粘贴你针对本条告警准备的补发文案。";
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(sample).then(
        () => toast.success("已复制示例补发文案到剪贴板"),
        () => toast.info("演示：示例文案已就绪"),
      );
    } else {
      toast.info("演示：示例文案已就绪");
    }
  }
}

async function deleteTask(taskId: number) {
  if (!(await confirmDialog("确定删除这个监测任务？历史结果会一并删除。", { title: "删除监测任务" }))) return;
  try {
    await sidecar.client.delete(`/api/monitor/tasks/${taskId}`);
    toast.success("任务已删除");
    if (selectedTaskId.value === taskId) {
      selectedTaskId.value = null;
      taskResults.value = [];
    }
    await loadTasks(activeTab.value === "zhihu" ? "zhihu_question" : PLATFORM_TYPE[commentSubtab.value]);
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

// 正在抓取中的 task_id 集合 —— 立刻跑下发瞬间乐观加入，SSE 收到
// finished/failed 再删掉。状态列按这个集合优先渲染"抓取中…"。
// 用 Set + ref.trigger() 的写法太重，直接换成 Record<number, true> 走
// Vue 的浅响应，列表里有几十条任务也很轻。
const runningTaskIds = ref<Record<number, true>>({});
function markRunning(taskId: number) {
  runningTaskIds.value = { ...runningTaskIds.value, [taskId]: true };
}
function clearRunning(taskId: number) {
  if (runningTaskIds.value[taskId]) {
    const next = { ...runningTaskIds.value };
    delete next[taskId];
    runningTaskIds.value = next;
  }
}

async function runNow(taskId: number) {
  // 乐观先标记 —— 后端 run-now 同步返回 {queued:true}，但 SSE 的 started
  // 事件可能要等到 worker 线程拿到 slot 才发出来，中间空窗用户会以为
  // 没反应。先点亮 spinner，SSE 来了顺势接住，failed/finished 时清掉。
  markRunning(taskId);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${taskId}/run-now`);
    toast.info("已派发，正在监测…");
  } catch (e: any) {
    clearRunning(taskId);
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`派发失败：${detail}`);
  }
}

// L1 批次批量派发：取该批次下所有子 task，并行 POST run-now。
// 后端有 per-platform Semaphore（默认 2 并发）+ pacer，前端一次性
// fire N 个不会冲风控；SSE finished 事件已经会对每个子任务调
// _fetchSnapshotPair，L1 行的留存/变化跟着自动刷，这里不重复 reload。
async function runBatch(batchName: string) {
  const child = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  if (!child.length) return;
  // 乐观先标 —— 按钮立刻切到 disabled "监测中…"，避免连点。
  child.forEach((t) => markRunning(t.id));
  const results = await Promise.allSettled(
    child.map((t) => sidecar.client.post(`/api/monitor/tasks/${t.id}/run-now`)),
  );
  const fails = results.filter((r) => r.status === "rejected");
  if (fails.length === 0) {
    toast.info(`已派发 ${child.length} 个任务`);
  } else if (fails.length === child.length) {
    // 全部失败 —— 这些任务永远不会有 SSE 事件进来清 spinner，手动清。
    child.forEach((t) => clearRunning(t.id));
    toast.error(`派发失败：${fails.length}/${child.length}`);
  } else {
    // 部分失败：只清掉失败那部分；成功的依然依赖 SSE 自然完成。
    results.forEach((r, i) => {
      if (r.status === "rejected") clearRunning(child[i].id);
    });
    toast.warn(`派发 ${child.length - fails.length}/${child.length}，${fails.length} 失败`);
  }
}

// 历史报告 drill-down 跳转 ── RetentionPage 行点击 emit navigate({platform, batchName, taskId}) → 这里。
// 切到平台评论 tab、平台 chip、批次 L2、视频 L3。靠 nextTick 等
// watch(activeTab) / watch(commentSubtab) 的 atomic-load 跑完
// 再设 selectedCommentTaskId/selectedVideoId，否则 atomic-load
// 内部的「selectedTaskId.value = newTasks[0].id」会盖掉我们的设置。
async function goToCommentTask(payload: {
  platform: "bilibili_comment" | "douyin_comment" | "kuaishou_comment";
  batchName: string;
  taskId: number;
}) {
  const subtabKey: CommentPlatform =
    payload.platform === "bilibili_comment" ? "bilibili"
    : payload.platform === "douyin_comment" ? "douyin"
    : "kuaishou";
  activeTab.value = "comment";
  commentSubtab.value = subtabKey;
  await nextTick();
  await nextTick();  // 一个 tick 不够；watch handler 是 async，等两 tick 让 atomic load 跑完
  selectedCommentTaskId.value = payload.batchName;
  selectedVideoId.value = `task-${payload.taskId}`;
}

async function goToZhihuTask(payload: { taskId: number }) {
  activeTab.value = "zhihu";
  await nextTick();
  await nextTick();
  selectedTaskId.value = payload.taskId;
}

function goToBaiduTask(_payload: { taskId: number }) {
  // MVP: switch to baidu workspace tab. User can then click the task row there.
  activeTab.value = "baidu";
}

// 批次按钮文案 / 禁用态。点击瞬间 markRunning 把所有子 task 全部
// 标为 running → 显示"监测中…"；SSE finished 逐个清除 → 数字递增
// 显示"监测中 1/5"、"监测中 2/5"…；归零后回到"立刻监测"。
function batchRunState(batchName: string): { label: string; disabled: boolean } {
  const child = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  const total = child.length;
  const runningCount = child.filter((t) => runningTaskIds.value[t.id]).length;
  if (runningCount === 0) return { label: "立刻监测", disabled: false };
  if (runningCount === total) return { label: "监测中…", disabled: true };
  return { label: `监测中 ${total - runningCount}/${total}`, disabled: true };
}

let stopMonitorBus: (() => void) | null = null;
function startMonitorBus() {
  stopMonitorBus = subscribe("/api/monitor/events", {
    started: (d: any) => {
      // adapter 真正开始 fetch 了 —— 把 spinner 接住（runNow 也会乐观标，
      // 这里只是兜底：定时调度的任务也能在 UI 上看见正在跑）。
      if (typeof d.task_id === "number" && d.task_id > 0) markRunning(d.task_id);
    },
    finished: (d: any) => {
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) {
        t.last_check_at = d.at;
        t.last_status = d.result?.status ?? t.last_status;
      }
      if (selectedTaskId.value === d.task_id) {
        loadResults(d.task_id);
      }
      // 抓完一条立刻刷它的 latest/prev snapshot —— 评论 tab 用来更新
      // 留存/被删评论列表；知乎 tab 用来更新"上次/变化"列。
      if (activeTab.value === "zhihu" || activeTab.value === "comment") {
        _fetchSnapshotPair(d.task_id);
      }
      clearRunning(d.task_id);
    },
    alert: (d: any) => {
      toast.warn(`任务 #${d.task_id} 触发告警`);
    },
    failed: (d: any) => {
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) t.last_status = "failed";
      clearRunning(d.task_id);
      const detail = d.error ? `：${String(d.error).split("\n")[0]}` : "";
      toast.error(`任务 #${d.task_id} 抓取失败${detail}`);
    },
    captcha_required: (d: any) => {
      toast.warn(
        `任务 #${d.task_id} 百度要求验证码 — 浏览器已弹出，请在 90 秒内完成验证`,
      );
    },
    captcha_resolved: (d: any) => {
      toast.success(`任务 #${d.task_id} 已通过验证码，继续抓取`);
    },
    captcha_timeout: (d: any) => {
      toast.error(`任务 #${d.task_id} 验证码等待超时，任务已标记为失败`);
    },
  });
}

const sparkPoints = computed(() => {
  if (demoMode.value) return SAMPLE_SPARK_RANK;
  const topN = cfg.data?.monitor?.alert_top_n ?? 5;
  return [...taskResults.value]
    .reverse()
    .map((r) => (r.rank > 0 ? r.rank : topN + 5));
});

watch(activeTab, async (t) => {
  if (t === "zhihu") {
    await loadTasksAndSnapshotsAtomic("zhihu_question");
  } else if (t === "comment") {
    await loadTasksAndSnapshotsAtomic(PLATFORM_TYPE[commentSubtab.value]);
  }
  // 历史报告 sub-page self-loads via RetentionPage / ZhihuRankingPage onMounted
});

watch(commentSubtab, async (s) => {
  if (activeTab.value !== "comment") return;
  await loadTasksAndSnapshotsAtomic(PLATFORM_TYPE[s]);
});

watch(selectedTaskId, async (id) => {
  if (id != null && id > 0) await loadResults(id);
});

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
);

// 知乎详情卡的 "Top 3 抢占者" —— 从 taskResults 的最新一次 result
// (`taskResults[0]`，按 checked_at desc 来) 的 `metric.answers` 取前 3。
// 每条 answer 由 zhihu_question 的 `_rank_brand` 写出，字段：rank /
// author / content_preview / voteup_count / matches_brand。matches_brand
// 标记的是命中目标品牌的那条，UI 上用 primary-soft 高亮。
interface ZhihuTopAnswer {
  rank: number;
  author: string;
  content_preview: string;
  voteup_count: number;
  matches_brand: boolean;
}
// 详情卡里展示的全部前 N 条答案。原来只取前 3（"Top 3 抢占者"），但
// 用户要求"前 N 条命中的都标记出来"，所以拿全量返回，模板用
// `.matches_brand` 高亮命中行。
const topAnswersForSelectedTask = computed<ZhihuTopAnswer[]>(() => {
  if (!selectedTask.value) return [];
  const latest = taskResults.value[0];
  const answers = latest?.metric?.answers;
  if (!Array.isArray(answers)) return [];
  return answers.map((a: any) => ({
    rank: Number(a.rank) || 0,
    author: String(a.author ?? ""),
    content_preview: String(a.content_preview ?? ""),
    voteup_count: Number(a.voteup_count) || 0,
    matches_brand: Boolean(a.matches_brand),
  }));
});

// 演示模式下的当前 zhihu 任务（用于详情卡片）。SAMPLE_ZHIHU 发布前已清空，
// 这里改为可空 ref；模板里详情卡用 v-if 守卫，没有示例数据就显示空状态。
const sampleSelectedZhihu = ref<SampleZhihu | null>(SAMPLE_ZHIHU[0] ?? null);

// 评论 tab 三级导航：
//   selectedCommentTaskId  —— 一级 → 二级（左列从任务列表换成视频列表）
//   selectedVideoId        —— 二级 → 三级（右列从汇总图换成单视频详情）
// 两者都是字符串 id，分别对应 commentRows / videosByBatchId 里的 id。
const selectedCommentTaskId = ref<string | null>(null);
const selectedVideoId = ref<string | null>(null);

// ── Real-data unifiers ────────────────────────────────────────────────
//
// 这一段是把后端真实 task + snapshot 数据"塑形"成原来 demo 用的
// SampleComment / VideoEntry 形状，让下面的 rich UI 模板不需要重写。
// 切换 demoMode 时只换数据源，不动模板。
//
// 任务名约定：批量导入产生的 task.name = `${batchName} - ${urlTail}`；
// 单条新增（AddTaskModal）的没有这层前缀。parseBatchName 用最后一个
// " - " 切，没切到就把整个 name 当作独立批次。
function parseBatchName(taskName: string): string {
  const idx = taskName.lastIndexOf(" - ");
  if (idx <= 0) return taskName;
  return taskName.slice(0, idx);
}

function _statusFromRatio(retained: number, total: number): "ok" | "warn" | "alert" {
  if (total === 0) return "ok";
  const ratio = retained / total;
  if (ratio >= 0.9) return "ok";
  if (ratio >= 0.6) return "warn";
  return "alert";
}

function _formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  if (Number.isNaN(diffMs)) return "—";
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} 小时前`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days} 天前`;
  return d.toLocaleDateString();
}

// L1 任务行 —— 把 tasks 按 batchName 聚合
const realCommentRows = computed<SampleComment[]>(() => {
  if (demoMode.value) return [];
  // group tasks by batch name
  const byBatch = new Map<string, Task[]>();
  for (const t of tasks.value) {
    const b = parseBatchName(t.name);
    const arr = byBatch.get(b) ?? [];
    arr.push(t);
    byBatch.set(b, arr);
  }
  const out: SampleComment[] = [];
  for (const [batchName, batchTasks] of byBatch) {
    let matchedNow = 0;
    let matchedPrev = 0;
    let havePrev = false;
    let latestCheck: string | null = null;
    for (const t of batchTasks) {
      const pair = taskSnapshots.value[t.id];
      if (pair?.latest?.matched) matchedNow++;
      if (pair?.prev) {
        havePrev = true;
        if (pair.prev.matched) matchedPrev++;
      }
      const ts = pair?.latest?.checked_at || t.last_check_at;
      if (ts && (!latestCheck || ts > latestCheck)) latestCheck = ts;
    }
    out.push({
      id: batchName,
      kw: batchName,
      lastChecked: _formatRelativeTime(latestCheck),
      retained: matchedNow,
      total: batchTasks.length,
      delta: havePrev ? matchedNow - matchedPrev : 0,
      status: _statusFromRatio(matchedNow, batchTasks.length),
    });
  }
  // 按状态严重度 → 留存率升序排：先看告警的
  const severityOrder = { alert: 0, warn: 1, ok: 2 } as const;
  out.sort((a, b) => {
    const s = severityOrder[a.status] - severityOrder[b.status];
    if (s !== 0) return s;
    const ra = a.total ? a.retained / a.total : 1;
    const rb = b.total ? b.retained / b.total : 1;
    return ra - rb;
  });
  return out;
});

// L2 视频列表 —— 把每个批次内的 tasks 塑形成 VideoEntry
//
// 状态规则（与后端 alert_top_n / scrape_top_n 拆分对齐）：
//   matched && rank <= alert_top_n → "ok"      在显且在理想范围内
//   matched && rank >  alert_top_n → "folded"  在显但跌出理想（前端文案"跌出 #N"）
//   !matched                        → "deleted" 没在前 scrape_top_n 条命中（被删 / 折叠 / 没爬到均落此态，UI 显示"无 / 未找到"）
const realVideosByBatchId = computed<Record<string, VideoEntry[]>>(() => {
  if (demoMode.value) return {};
  const map: Record<string, VideoEntry[]> = {};
  for (const t of tasks.value) {
    const b = parseBatchName(t.name);
    const snap = taskSnapshots.value[t.id]?.latest;
    const matched = snap?.matched ?? false;
    const rank = snap?.rank ?? -1;
    const alertN = snap?.alert_top_n ?? 5;
    const status: VideoEntry["status"] =
      matched
        ? rank > 0 && rank <= alertN ? "ok" : "folded"
        : "deleted";
    const urlTail = t.name.includes(" - ")
      ? t.name.slice(t.name.lastIndexOf(" - ") + 3)
      : t.name;
    const entry: VideoEntry = {
      id: `task-${t.id}`,
      url: t.target_url,
      title: urlTail || t.target_url,
      myComment: snap?.my_comment_text ?? "—",
      rank: rank > 0 ? rank : 0,
      status,
      postedAt: t.last_check_at ? new Date(t.last_check_at).toLocaleDateString() : "—",
      totalComments: snap?.total_fetched ?? 0,
    };
    (map[b] ||= []).push(entry);
  }
  return map;
});

// 把 video.id 反查回 task.id 用，L3 单视频 SSE / 立刻跑要原数字 id
function realTaskIdFromVideoId(videoId: string): number | null {
  const m = /^task-(\d+)$/.exec(videoId);
  return m ? Number(m[1]) : null;
}

// 留存趋势 sparkline —— 用 task.id 维度的"每次检查 matched 占比"作为
// 一条折线。真实数据下，未选批次时聚合所有任务、选中批次时只聚合该批次。
//
// 简化：用每条 task 的最近 N 次 result（已经 fetch 了 latest+prev，再
// 临时拉 limit=14）；按 checked_at 桶 7 天。先用 latest+prev 两点做兜底
// （能看到趋势但不够细），后面想细可以再拉历史。
const realRetentionPoints = computed<number[]>(() => {
  if (demoMode.value) return [];
  // 选中批次时只看该批次
  const scope: Task[] = selectedCommentTaskId.value
    ? tasks.value.filter((t) => parseBatchName(t.name) === selectedCommentTaskId.value)
    : tasks.value;
  if (!scope.length) return [];
  // 两个点：prev 与 latest 的 matched 占比 ×100
  let mNow = 0, nNow = 0, mPrev = 0, nPrev = 0;
  for (const t of scope) {
    const pair = taskSnapshots.value[t.id];
    if (pair?.latest) {
      nNow++;
      if (pair.latest.matched) mNow++;
    }
    if (pair?.prev) {
      nPrev++;
      if (pair.prev.matched) mPrev++;
    }
  }
  const points: number[] = [];
  if (nPrev > 0) points.push(Math.round((mPrev / nPrev) * 100));
  if (nNow > 0) points.push(Math.round((mNow / nNow) * 100));
  // 单点没法画线；补一个相同值让 sparkline 不至于空
  if (points.length === 1) points.unshift(points[0]);
  return points;
});

// 被删评论列表 —— scope 同上：未选批次=所有任务、选中批次=该批次
const realDeletedComments = computed(() => {
  if (demoMode.value) return [] as Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }>;
  const scope: Task[] = selectedCommentTaskId.value
    ? tasks.value.filter((t) => parseBatchName(t.name) === selectedCommentTaskId.value)
    : tasks.value;
  const items: Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }> = [];
  for (const t of scope) {
    const snap = taskSnapshots.value[t.id]?.latest;
    if (!snap) continue;
    if (snap.matched) continue; // 留存中，跳过
    // 抢占者：matched=false 时 hot_comments[0] 就是 top1（不是我）
    const top1 = snap.hot_comments?.[0];
    const grabber = top1?.author || top1?.nickname || "—";
    const tone: "alert" | "warn" = snap.rank > 0 ? "warn" : "alert";
    items.push({
      tag: tone === "alert" ? "被删" : "折叠",
      who: `@${grabber}（${snap.my_comment_text.slice(0, 16)}${snap.my_comment_text.length > 16 ? "…" : ""}）`,
      date: snap.checked_at ? new Date(snap.checked_at).toLocaleDateString() : "—",
      tone,
    });
  }
  // 最近发生的排前面
  items.sort((a, b) => (a.date < b.date ? 1 : -1));
  return items;
});

// ── Unified data source ──────────────────────────────────────────────
// 模板里统一引用这 4 个 computed —— demoMode 时拿示例、否则拿真实数据。
// 这样模板不需要 v-if="demoMode" 来回切两套布局。
const commentRows = computed<SampleComment[]>(() =>
  demoMode.value ? SAMPLE_COMMENTS[commentSubtab.value] : realCommentRows.value,
);
const videosByBatchId = computed<Record<string, VideoEntry[]>>(() =>
  demoMode.value ? SAMPLE_VIDEOS : realVideosByBatchId.value,
);
const retentionPoints = computed<number[]>(() =>
  demoMode.value ? SAMPLE_RETENTION : realRetentionPoints.value,
);
const deletedComments = computed(() =>
  demoMode.value ? SAMPLE_DELETED : realDeletedComments.value,
);

const selectedCommentRow = computed(() =>
  selectedCommentTaskId.value
    ? commentRows.value.find((c) => c.id === selectedCommentTaskId.value) ?? null
    : null,
);
const selectedTaskVideos = computed<VideoEntry[]>(() =>
  selectedCommentTaskId.value
    ? videosByBatchId.value[selectedCommentTaskId.value] ?? []
    : [],
);
const selectedVideo = computed<VideoEntry | null>(() => {
  if (!selectedVideoId.value) return null;
  return selectedTaskVideos.value.find((v) => v.id === selectedVideoId.value) ?? null;
});

// ── 告警 hero（zhihu / comment）computed ───────────────────────────────
//
// V1 设计稿那条红黑底「N 个紧急告警」卡片之前 zhihuAlerts/commentAlerts
// 是硬编码 []，永远不显示。这里从真实数据派生：
//
//   zhihu  ⇒ task 撞 failed / risk_control / 排名掉出 top_n / 排名暴跌 ≥6
//   comment⇒ batch 整体 status === "alert"（留存率 < 60%）
//
// 一类任务最多堆 3 张 hero（match 设计稿的卡片堆叠），多了用户在 chevron
// 之间切。空时 hero 整段不显示。
const zhihuAlerts = computed<HeroAlert[]>(() => {
  if (demoMode.value || activeTab.value !== "zhihu") return [];
  const out: HeroAlert[] = [];
  for (const t of tasks.value) {
    const pair = taskSnapshots.value[t.id];
    const snap = pair?.latest;
    const prev = pair?.prev;
    let headline = "";
    if (t.last_status === "failed") headline = "抓取失败";
    else if (t.last_status === "risk_control") headline = "触发风控";
    else if (snap && snap.rank === -1) {
      const topN = snap.total_fetched > 0 ? snap.total_fetched : 10;
      headline = `已掉出前 ${topN}`;
    } else if (snap && prev && prev.rank > 0 && snap.rank > 0 && snap.rank - prev.rank >= 6) {
      headline = `跌 ${snap.rank - prev.rank} 名 · 现 #${snap.rank}`;
    } else {
      continue;
    }
    out.push({
      keyword: t.name,
      headline,
      subtitle: `上次检查 ${_formatRelativeTime(snap?.checked_at || t.last_check_at)}`,
      taskId: t.id,
    });
    if (out.length >= 3) break;
  }
  return out;
});

const commentAlerts = computed<HeroAlert[]>(() => {
  if (demoMode.value || activeTab.value !== "comment") return [];
  const out: HeroAlert[] = [];
  for (const r of realCommentRows.value) {
    if (r.status !== "alert") continue;
    const dropped = r.total - r.retained;
    const ratio = r.total > 0 ? Math.round((r.retained / r.total) * 100) : 0;
    out.push({
      keyword: r.kw,
      headline: `评论被删 ${dropped} 条 · 留存跌至 ${ratio}%`,
      subtitle: `${r.lastChecked} · ${r.total} 条视频`,
      batchName: r.id,
    });
    if (out.length >= 3) break;
  }
  return out;
});

function openCommentDetail(taskId: string) {
  selectedCommentTaskId.value = taskId;
  selectedVideoId.value = null; // 进二级先清三级，避免脏数据
}
function backToCommentList() {
  selectedCommentTaskId.value = null;
  selectedVideoId.value = null;
}
function selectVideo(videoId: string) {
  selectedVideoId.value = videoId;
}
function closeVideoDetail() {
  selectedVideoId.value = null;
}
// 切平台时清掉二级/三级选中，避免拿着 B 站的 task id 误展示在抖音/快手。
watch(commentSubtab, () => {
  selectedCommentTaskId.value = null;
  selectedVideoId.value = null;
});

function severity(t: Task): "alert" | "warn" | "ok" | "info" {
  if (!t.last_status) return "info";
  if (t.last_status === "failed" || t.last_status === "risk_control") return "alert";
  if (t.last_status !== "ok") return "info";
  return "ok";
}
const STATUS_LABEL: Record<string, string> = {
  alert: "异常",
  warn: "跌出",
  ok: "稳定",
  info: "未检",
};

// 任务类型 → 中文显示。Task.type 后端用英文 enum (zhihu_question / *_comment)，
// 但列表/详情卡里给用户看的应该是中文，跟 AddTaskModal 的 TYPES 标签对齐。
const TYPE_LABEL: Record<string, string> = {
  zhihu_question: "知乎问题",
  bilibili_comment: "B 站评论",
  douyin_comment: "抖音评论",
  kuaishou_comment: "快手评论",
  baidu_keyword: "百度关键词",
};
function typeLabel(t: string): string {
  return TYPE_LABEL[t] ?? t;
}

// tabCounts 计数徽章已下线（顶部 pivot 不再展示 4/1/12 数字胶囊）；
// 如需重启回归，把上面的 pill 模板 + 这里的 computed 一起恢复。

onMounted(async () => {
  try {
    await whenReady();
    if (!cfg.data) await cfg.load();
    if (activeTab.value === "zhihu") {
      await loadTasks("zhihu_question");
      await loadTaskSnapshots();
    } else if (activeTab.value === "comment") {
      await loadTasks(PLATFORM_TYPE[commentSubtab.value]);
      await loadTaskSnapshots();
    }
    // 历史报告 sub-page self-loads via RetentionPage / ZhihuRankingPage onMounted
    startMonitorBus();
  } catch {
    /* sidecar already toasted; demoMode 会接管显示 */
    failed.value = true;
  }
});

onUnmounted(() => {
  if (stopMonitorBus) stopMonitorBus();
});

// 面板交互：点击演示行切换详情卡
function pickSampleZhihu(row: SampleZhihu) {
  sampleSelectedZhihu.value = row;
}

const TAB_META: Array<{ k: Tab; l: string; ic: string }> = [
  { k: "zhihu", l: "知乎问题", ic: "radar" },
  { k: "comment", l: "平台评论", ic: "warn" },
  { k: "baidu", l: "百度排名", ic: "search" },
  { k: "report", l: "历史报告", ic: "fileText" },
];
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '24px' }">
    <!-- ── 顶部：title + pivot ───────────────────────────────────── -->
    <div class="flex flex-shrink-0 items-end justify-between gap-4">
      <div class="min-w-0">
        <div
          class="text-[11px] uppercase"
          :style="{ letterSpacing: '1.5px', color: 'var(--ink-3)' }"
        >监测中心</div>
        <div
          class="font-display mt-2 font-bold"
          :style="{ fontSize: '30px', letterSpacing: '-0.5px' }"
        >
          {{
            activeTab === "zhihu"
              ? "知乎问题 · 问题监控"
              : activeTab === "comment"
                ? "平台评论 · 留存监控"
                : activeTab === "baidu"
                  ? "百度排名 · 关键词监控"
                  : "历史监测报告"
          }}
        </div>
        <div class="mt-1 text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
          {{
            activeTab === "zhihu"
              ? "知乎问题 · 关键词排名 + Top 抢占者"
              : activeTab === "comment"
                ? "B 站 / 抖音 / 快手 · 评论被删与折叠告警"
                : activeTab === "baidu"
                  ? "百度搜索 · 默认 + 最新资讯 · 自家命中"
                  : "日报 · 周报 · 按时间倒序"
          }}
        </div>
      </div>

      <div
        class="flex flex-shrink-0 items-center"
        :style="{
          background: 'var(--card)',
          borderRadius: '999px',
          padding: '4px',
          border: '1px solid var(--line)',
        }"
      >
        <button
          v-for="t in TAB_META"
          :key="t.k"
          type="button"
          class="inline-flex items-center"
          :style="{
            height: '32px',
            padding: '0 16px',
            borderRadius: '999px',
            background: activeTab === t.k ? 'var(--dark)' : 'transparent',
            color: activeTab === t.k ? '#fbf7ec' : 'var(--ink-3)',
            fontSize: '12.5px',
            fontWeight: 500,
            gap: '6px',
            transition: 'background .15s, color .15s',
          }"
          @click="activeTab = t.k"
        >
          <!--
            原来 t.l 后面跟一颗 `tabCounts[t.k]` 数字胶囊（4 / 1 / 12），
            被用户判定为无信息价值 —— 总条数对决策没帮助，反而让 pill
            视觉变长。删掉，pill 只剩 icon + 名称。
          -->
          <Icon :name="t.ic" :size="13" />
          <span>{{ t.l }}</span>
        </button>
      </div>
    </div>

    <!-- ── 知乎问题 ─────────────────────────────────────────────── -->
    <template v-if="activeTab === 'zhihu'">
      <!--
        告警 hero 包裹层 —— 当告警数 > 1 时，hero 下方再放 1–2 张更窄
        更暗的「影子」卡，形成卡片堆叠的视觉；点右上角的 ‹ › 切换上一
        条 / 下一条。1 条时 hasNav=false，影子和按钮一起隐藏。
      -->
      <div
        v-if="zhihuAlerts.length > 0 && currentZhihuAlert"
        class="relative flex-shrink-0"
        :style="{ paddingBottom: zhihuAlerts.length > 1 ? '14px' : '0' }"
      >
        <!-- 影子卡片 #1 (2nd) — 比 hero 窄 16px，下偏 6px，更暗 -->
        <div
          v-if="zhihuAlerts.length > 1"
          aria-hidden="true"
          :style="{
            position: 'absolute',
            left: '8px',
            right: '8px',
            top: '8px',
            bottom: '0',
            background: 'var(--dark)',
            opacity: 0.55,
            borderRadius: 'var(--radius-card)',
            transform: 'translateY(0)',
            zIndex: 0,
          }"
        />
        <!-- 影子卡片 #2 (3rd) — 再窄 16px -->
        <div
          v-if="zhihuAlerts.length > 2"
          aria-hidden="true"
          :style="{
            position: 'absolute',
            left: '16px',
            right: '16px',
            top: '14px',
            bottom: '-6px',
            background: 'var(--dark)',
            opacity: 0.3,
            borderRadius: 'var(--radius-card)',
            zIndex: 0,
          }"
        />
        <!-- 真正的 hero -->
        <div
          class="relative overflow-hidden"
          :style="{
            background: 'var(--dark)',
            color: '#fbf7ec',
            borderRadius: 'var(--radius-card)',
            padding: '26px 28px',
            zIndex: 1,
          }"
        >
          <div
            aria-hidden="true"
            :style="{
              position: 'absolute',
              top: '-50px', left: '20px',
              width: '240px', height: '240px',
              background: 'radial-gradient(circle, rgba(216,90,72,0.55), transparent 65%)',
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
              background: 'radial-gradient(circle, rgba(238,106,42,0.45), transparent 65%)',
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
                <span>{{ zhihuAlerts.length }} 个紧急告警</span>
                <span
                  v-if="zhihuAlerts.length > 1"
                  :style="{ color: 'rgba(255,255,255,0.4)', letterSpacing: '0' }"
                >· {{ zhihuAlertIdx + 1 }} / {{ zhihuAlerts.length }}</span>
              </div>
              <div
                class="font-display mt-2 font-bold"
                :style="{ fontSize: '28px', letterSpacing: '-0.5px', lineHeight: '1.25' }"
              >
                「{{ currentZhihuAlert.keyword }}」<br />
                <span :style="{ color: 'var(--primary)' }">{{ currentZhihuAlert.headline }}</span>
              </div>
              <div class="mt-2 text-[12.5px]" :style="{ color: 'rgba(255,255,255,0.6)' }">
                {{ currentZhihuAlert.subtitle }}
              </div>
            </div>
            <div class="flex flex-shrink-0 items-center gap-2">
              <!-- prev / next chevrons (only when > 1 alert) -->
              <template v-if="zhihuAlerts.length > 1">
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
                  @click="cycleAlert('zhihu', -1)"
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
                  @click="cycleAlert('zhihu', 1)"
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
                @click="openZhihuAlert(currentZhihuAlert)"
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
                <span>起一篇救场</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- table + detail -->
      <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
        <!-- table card -->
        <section
          class="flex h-full flex-col"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="font-display text-[14px] font-semibold">监测任务</div>
              <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                按上次检查倒序
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
                @click="showCookieMgr = true"
              >
                <Icon name="key" :size="12" />
                <span>Cookie</span>
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px]"
                :style="{
                  background: 'transparent',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '999px',
                }"
                @click="showBatchImport = true"
              >
                <Icon name="folder" :size="12" />
                <span>批量导入</span>
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
                :style="{
                  background: 'var(--primary)',
                  color: '#fff',
                  borderRadius: '999px',
                }"
                @click="showAddTask = true"
              >
                <Icon name="plus" :size="12" />
                <span>新增任务</span>
              </button>
            </div>
          </div>

          <!-- scrollable table body — fills remaining vertical space -->
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <!-- header row -->
          <div
            class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
            :style="{
              gridTemplateColumns: '1.6fr .7fr .5fr .5fr 1.4fr',
              letterSpacing: '1.2px',
              color: 'var(--ink-3)',
              borderBottom: '1px solid var(--line)',
            }"
          >
            <div>问题名字</div><div>类型</div><div>上次</div><div>变化</div><div>状态</div>
          </div>

          <!-- demo empty state — SAMPLE_ZHIHU 发布前已清空，首次启动展示空态 -->
          <template v-if="demoMode && SAMPLE_ZHIHU.length === 0">
            <div
              class="py-10 text-center text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              暂无监测任务 · 点击「新增任务」开始监测
            </div>
          </template>

          <!-- demo rows -->
          <template v-else-if="demoMode">
            <div
              v-for="(t, i) in SAMPLE_ZHIHU"
              :key="t.id"
              class="grid cursor-pointer items-center transition"
              :style="{
                gridTemplateColumns: '1.6fr .7fr .5fr .5fr 1.4fr',
                background: sampleSelectedZhihu?.id === t.id ? 'var(--card-2)' : 'transparent',
                borderBottom: i < SAMPLE_ZHIHU.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '14px 8px',
                borderRadius: '10px',
              }"
              @click="pickSampleZhihu(t)"
            >
              <div class="truncate text-[13px] font-medium">{{ t.kw }}</div>
              <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">{{ typeLabel(t.type) }}</div>
              <div class="font-display text-[13px] font-bold">
                {{ t.lastRank == null ? "—" : `#${t.lastRank}` }}
              </div>
              <div>
                <Pill v-if="t.delta > 0" tone="ok">
                  <Icon name="arrowUp" :size="10" />
                  +{{ t.delta }}
                </Pill>
                <Pill v-else-if="t.delta < 0 && t.delta > -10" tone="warn">
                  <Icon name="arrowDown" :size="10" />
                  {{ t.delta }}
                </Pill>
                <Pill v-else-if="t.delta === 0" tone="info">持平</Pill>
                <Pill v-else tone="alert">
                  <Icon name="warn" :size="10" />
                  掉出
                </Pill>
              </div>
              <div>
                <Pill v-if="t.status === 'ok'" tone="ok">正常</Pill>
                <Pill v-else-if="t.status === 'warn'" tone="warn">关注</Pill>
                <Pill v-else tone="alert">告警</Pill>
              </div>
            </div>
          </template>

          <!-- real rows —— 与 demo 5 列对齐：名字 / 类型 / 上次 / 变化 / 状态+操作 -->
          <!--
            状态+操作那一列要容纳 pill + "立刻监测" + 编辑 + 删除 4 个元
            素，原来 .6fr 太窄会把"立刻监测"压成两行。最后一列改成 1.4fr
            （是 .6fr 的 2 倍多），其它列等比缩窄，名字仍最宽。
          -->
          <template v-else>
            <div
              v-for="(t, i) in tasks"
              :key="t.id"
              class="grid cursor-pointer items-center transition"
              :style="{
                gridTemplateColumns: '1.6fr .7fr .5fr .5fr 1.4fr',
                background: selectedTaskId === t.id ? 'var(--card-2)' : 'transparent',
                borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '14px 8px',
                borderRadius: '10px',
              }"
              @click="selectedTaskId = t.id"
            >
              <div class="truncate text-[13px] font-medium">{{ t.name }}</div>
              <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">{{ typeLabel(t.type) }}</div>
              <!--
                上次：知乎现在主要看"命中数 / Top-N"（例如 3 / 10），
                有命中时下面再附一行最高位 #N；0 命中显"前 N 以外"。
                这跟用户描述完全对齐："前十里包含关键词的数量，标出来；
                没有就标前十以外"。
              -->
              <div class="font-display text-[13px] font-bold">
                <template v-if="taskSnapshots[t.id]?.latest">
                  <template v-if="taskSnapshots[t.id]!.latest!.matched_count > 0">
                    <span>
                      {{ taskSnapshots[t.id]!.latest!.matched_count }} /
                      {{ taskSnapshots[t.id]!.latest!.alert_top_n }}
                    </span>
                    <div
                      class="text-[10.5px] font-normal"
                      :style="{ color: 'var(--ink-3)', marginTop: '1px' }"
                    >最高 #{{ taskSnapshots[t.id]!.latest!.rank }}</div>
                  </template>
                  <span
                    v-else
                    :style="{ color: 'var(--red, #d85a48)', fontSize: '12px', fontWeight: 'normal' }"
                  >前 {{ taskSnapshots[t.id]!.latest!.alert_top_n }} 以外</span>
                </template>
                <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
              </div>
              <!--
                变化：用命中数 delta 而不是 rank delta —— 用户的心智模型
                是"我们家这次有几条上榜、上次有几条"。+1 = 多一条占位，
                -1 = 少一条；持平不显 pill。
              -->
              <div>
                <template v-if="taskSnapshots[t.id]?.latest && taskSnapshots[t.id]?.prev">
                  <template
                    v-if="taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count > 0"
                  >
                    <Pill tone="ok">
                      <Icon name="arrowUp" :size="10" />
                      +{{ taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count }}
                    </Pill>
                  </template>
                  <template
                    v-else-if="taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count < 0"
                  >
                    <Pill tone="warn">
                      <Icon name="arrowDown" :size="10" />
                      {{ taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count }}
                    </Pill>
                  </template>
                  <Pill v-else tone="info">持平</Pill>
                </template>
                <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
              </div>
              <!--
                状态 + 操作 —— pill 左对齐，操作按钮组靠右用 justify-between
                + 拆成两块，比 justify-end 一锅端的视觉重量更均衡。"立刻监测"
                加 whitespace-nowrap 杜绝换行；按钮组之间用 gap-1 而不是
                gap-1.5，跟 pill 区别度更大。
              -->
              <div class="flex items-center justify-between gap-2">
                <span
                  v-if="runningTaskIds[t.id]"
                  class="inline-flex flex-shrink-0 items-center gap-1.5 text-[11px]"
                  :style="{
                    color: 'var(--primary-deep)',
                    background: 'var(--primary-soft)',
                    border: '1px solid rgba(238,106,42,0.25)',
                    padding: '2px 8px',
                    borderRadius: '999px',
                  }"
                  title="正在监测，请稍候"
                >
                  <Spinner :size="10" />
                  <span class="whitespace-nowrap">监测中…</span>
                </span>
                <!--
                  状态 pill 优先看 snapshot.matched_count（命中数语义比
                  原 severity 那条"last_status==ok 一律稳定"准确）：
                    matched_count > 0 → 上榜（绿）
                    matched_count == 0 → 未上榜（红）
                    没快照 / 抓取失败 → 回退 severity()
                -->
                <template v-if="taskSnapshots[t.id]?.latest && t.last_status === 'ok'">
                  <Pill
                    v-if="taskSnapshots[t.id]!.latest!.matched_count > 0"
                    tone="ok"
                  >上榜</Pill>
                  <Pill v-else tone="alert">未上榜</Pill>
                </template>
                <Pill v-else :tone="severity(t)">{{ STATUS_LABEL[severity(t)] }}</Pill>
                <div class="flex flex-shrink-0 items-center gap-0.5">
                  <button
                    type="button"
                    class="whitespace-nowrap text-[11px]"
                    :style="{
                      padding: '4px 10px',
                      borderRadius: '999px',
                      color: runningTaskIds[t.id] ? 'var(--ink-3)' : 'var(--primary-deep)',
                      cursor: runningTaskIds[t.id] ? 'not-allowed' : 'pointer',
                    }"
                    :disabled="!!runningTaskIds[t.id]"
                    @click.stop="runNow(t.id)"
                  >{{ runningTaskIds[t.id] ? "监测中" : "立刻监测" }}</button>
                  <button
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--ink-3)',
                    }"
                    title="编辑任务（目标关键词 / Top-N / 计划）"
                    @click.stop="openEditTask(t)"
                  >
                    <Icon name="edit" :size="13" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--ink-3)',
                    }"
                    title="删除任务"
                    @click.stop="deleteTask(t.id)"
                  >
                    <Icon name="trash" :size="13" />
                  </button>
                </div>
              </div>
            </div>
          </template>
          </div>
        </section>

        <!-- detail card -->
        <section
          class="flex h-full flex-col overflow-y-auto"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <template v-if="demoMode && !sampleSelectedZhihu">
            <div class="py-6 text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
              点击左侧任意任务查看详情。
            </div>
          </template>
          <template v-else-if="demoMode && sampleSelectedZhihu">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="font-display text-[14px] font-semibold">
                  「{{ sampleSelectedZhihu.kw }}」
                </div>
                <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                  {{ sampleSelectedZhihu.type }}
                </div>
              </div>
              <a
                :href="sampleSelectedZhihu.targetUrl"
                target="_blank"
                rel="noopener"
                class="inline-flex flex-shrink-0 items-center gap-1 px-3 py-1.5 text-[11.5px]"
                :style="{
                  background: 'var(--card-2)',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '999px',
                  textDecoration: 'none',
                }"
                title="在浏览器打开知乎问题"
              >
                <Icon name="external" :size="12" />
                <span>问题链接</span>
              </a>
            </div>

            <div class="mt-3 grid grid-cols-3 gap-3">
              <div
                v-for="s in [
                  { l: '当前排名', v: sampleSelectedZhihu.lastRank == null ? '—' : `#${sampleSelectedZhihu.lastRank}` },
                  { l: '上次排名', v: `#${sampleSelectedZhihu.prevRank}` },
                  { l: '检查频率', v: '每 6 小时' },
                ]"
                :key="s.l"
                :style="{
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ s.l }}</div>
                <div
                  class="font-display mt-1 font-bold"
                  :style="{ fontSize: '18px' }"
                >{{ s.v }}</div>
              </div>
            </div>

            <div class="mt-5">
              <div class="mb-2 text-[12px] font-semibold">最近 14 次快照</div>
              <Sparkline
                :points="sparkPoints"
                :width="380"
                :height="70"
                stroke="var(--red, #d85a48)"
                :axis-labels="ZHIHU_SPARK_LABELS"
                fluid
              />
            </div>

            <div class="mt-4">
              <div class="mb-2 text-[12px] font-semibold">Top 3 抢占者</div>
              <div
                v-for="(x, i) in SAMPLE_TOP3"
                :key="i"
                class="mb-1.5 flex items-center gap-3"
                :style="{
                  padding: '10px',
                  borderRadius: '10px',
                  background: i === 0 ? 'var(--primary-soft)' : 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <span
                  class="font-display text-[13px] font-bold"
                  :style="{
                    width: '22px',
                    color: i === 0 ? 'var(--primary-deep)' : 'var(--ink-2)',
                  }"
                >#{{ x.rank }}</span>
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[12.5px] font-medium">{{ x.title }}</div>
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ x.who }}</div>
                </div>
                <Icon name="arrowRight" :size="13" class="opacity-50" />
              </div>
            </div>

            <!-- 启停监测 + 频率设置 —— 部分任务可能没设定时；这里直接调。 -->
            <div
              class="mt-4 flex flex-shrink-0 items-center gap-2"
              :style="{
                paddingTop: '14px',
                borderTop: '1px solid var(--line)',
              }"
            >
              <button
                type="button"
                class="inline-flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-[12px] font-medium"
                :style="{
                  background: ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'var(--card-2)' : 'var(--primary)',
                  color: ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'var(--ink)' : '#fff',
                  border: '1px solid ' + (ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'var(--line)' : 'var(--primary)'),
                  borderRadius: '999px',
                }"
                :title="ensureZhihuState(sampleSelectedZhihu.id).enabled ? '点击暂停监测' : '点击启动监测'"
                @click="toggleMonitor('zhihu', sampleSelectedZhihu.id)"
              >
                <Icon
                  :name="ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'check' : 'play'"
                  :size="13"
                />
                <span>
                  {{ ensureZhihuState(sampleSelectedZhihu.id).enabled ? '监测进行中' : '启动监测' }}
                </span>
              </button>
              <!--
                监测定时：图标 + 文字 label 单独站一列，FormSelect 用自带
                的胶囊样式 —— 不再套一层有 bg/border 的外胶囊（之前那层是
                给原生 <select> 兜底的，FormSelect 已经自带卡片底了，叠
                两层会出现"框中框"双胶囊。
              -->
              <div class="flex flex-1 items-center gap-2">
                <Icon
                  name="calendar"
                  :size="13"
                  :style="{ color: 'var(--ink-3)' }"
                />
                <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">监测定时</span>
                <FormSelect
                  :model-value="ensureZhihuState(sampleSelectedZhihu.id).schedule"
                  :options="SCHEDULE_OPTIONS"
                  width="140"
                  @update:model-value="(v) => changeSchedule('zhihu', sampleSelectedZhihu!.id, String(v))"
                />
              </div>
            </div>
          </template>

          <template v-else>
            <div v-if="!selectedTask" class="text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
              点击左侧任意任务查看详情。
            </div>
            <template v-else>
              <!-- 头：问题名 + 链接 + 编辑 -->
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="font-display text-[14px] font-semibold">「{{ selectedTask.name }}」</div>
                  <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                    {{ typeLabel(selectedTask.type) }}
                  </div>
                </div>
                <div class="flex flex-shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 px-3 py-1.5 text-[11.5px]"
                    :style="{
                      background: 'var(--card-2)',
                      color: 'var(--ink-2)',
                      border: '1px solid var(--line)',
                      borderRadius: '999px',
                    }"
                    title="编辑目标关键词 / Top-N / 计划"
                    @click="openEditTask(selectedTask)"
                  >
                    <Icon name="edit" :size="12" />
                    <span>编辑</span>
                  </button>
                  <a
                    :href="selectedTask.target_url"
                    target="_blank"
                    rel="noopener"
                    class="inline-flex items-center gap-1 px-3 py-1.5 text-[11.5px]"
                    :style="{
                      background: 'var(--card-2)',
                      color: 'var(--ink-2)',
                      border: '1px solid var(--line)',
                      borderRadius: '999px',
                      textDecoration: 'none',
                    }"
                    title="在浏览器打开知乎问题"
                  >
                    <Icon name="external" :size="12" />
                    <span>问题链接</span>
                  </a>
                </div>
              </div>

              <!--
                KPI 三联：本次命中 / 上次命中 / 频率
                - "命中" = 前 N 条答案里包含目标品牌词的条数
                - 数字下方追加一行最高位（#1 表示自家答案排第 1）
                - 命中 0 → 红色 "前 N 以外"
              -->
              <div class="mt-3 grid grid-cols-3 gap-3">
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">本次命中</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
                    <template v-if="taskSnapshots[selectedTask.id]?.latest">
                      <template v-if="taskSnapshots[selectedTask.id]!.latest!.matched_count > 0">
                        <span>
                          {{ taskSnapshots[selectedTask.id]!.latest!.matched_count }} /
                          {{ taskSnapshots[selectedTask.id]!.latest!.alert_top_n }}
                        </span>
                        <div
                          class="mt-0.5 text-[10.5px] font-normal"
                          :style="{ color: 'var(--ink-3)' }"
                        >最高 #{{ taskSnapshots[selectedTask.id]!.latest!.rank }}</div>
                      </template>
                      <span
                        v-else
                        :style="{ color: 'var(--red, #d85a48)', fontSize: '14px' }"
                      >前 {{ taskSnapshots[selectedTask.id]!.latest!.alert_top_n }} 以外</span>
                    </template>
                    <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">上次命中</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
                    <template v-if="taskSnapshots[selectedTask.id]?.prev">
                      <template v-if="taskSnapshots[selectedTask.id]!.prev!.matched_count > 0">
                        <span>
                          {{ taskSnapshots[selectedTask.id]!.prev!.matched_count }} /
                          {{ taskSnapshots[selectedTask.id]!.prev!.alert_top_n }}
                        </span>
                      </template>
                      <span
                        v-else
                        :style="{ color: 'var(--ink-3)', fontSize: '14px' }"
                      >前 {{ taskSnapshots[selectedTask.id]!.prev!.alert_top_n }} 以外</span>
                    </template>
                    <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">检查频率</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '14px' }">
                    {{ selectedTask.schedule_cron === "manual" ? "手动" : selectedTask.schedule_cron }}
                  </div>
                </div>
              </div>

              <!-- 排名 sparkline -->
              <div class="mt-5">
                <div class="mb-2 text-[12px] font-semibold">最近 14 次排名</div>
                <Sparkline
                  v-if="sparkPoints.length"
                  :points="sparkPoints"
                  :width="380"
                  :height="70"
                  stroke="var(--red, #d85a48)"
                  :axis-labels="ZHIHU_SPARK_LABELS"
                  fluid
                />
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
                  无历史数据 —— 跑过几次"立刻监测"才能成线。
                </div>
              </div>

              <!--
                前 N 条答案 —— 从 taskResults[0].metric.answers 取全部。
                每条左侧带排名 #N，命中目标品牌的行用 primary-soft 背景 +
                橙色描边高亮，右侧角标"自家"。让用户一眼看出"前 N 条里
                我占了哪几位"——这是用户描述的核心需求。
              -->
              <div class="mt-4">
                <div class="mb-2 flex items-center justify-between">
                  <div class="text-[12px] font-semibold">
                    前
                    {{ taskSnapshots[selectedTask.id]?.latest?.alert_top_n ?? topAnswersForSelectedTask.length }}
                    条答案
                  </div>
                  <div
                    v-if="taskSnapshots[selectedTask.id]?.latest"
                    class="text-[11px]"
                    :style="{ color: 'var(--ink-3)' }"
                  >
                    自家命中
                    <span :style="{ color: 'var(--primary-deep)', fontWeight: 600 }">
                      {{ taskSnapshots[selectedTask.id]!.latest!.matched_count }}
                    </span>
                    条
                  </div>
                </div>
                <template v-if="topAnswersForSelectedTask.length">
                  <div
                    v-for="(x, i) in topAnswersForSelectedTask"
                    :key="i"
                    class="mb-1.5 flex items-center gap-3"
                    :style="{
                      padding: '10px',
                      borderRadius: '10px',
                      background: x.matches_brand ? 'var(--primary-soft)' : 'var(--card-2)',
                      border: '1px solid '
                        + (x.matches_brand ? 'rgba(238,106,42,0.3)' : 'var(--line)'),
                    }"
                  >
                    <span
                      class="font-display text-[13px] font-bold"
                      :style="{
                        width: '22px',
                        color: x.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)',
                      }"
                    >#{{ x.rank }}</span>
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-[12.5px] font-medium">
                        {{ x.content_preview || "（无摘要）" }}
                      </div>
                      <div class="flex items-center gap-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                        <span>{{ x.author || "—" }}</span>
                        <span v-if="x.voteup_count">· 👍 {{ x.voteup_count }}</span>
                        <span
                          v-if="x.matches_brand"
                          class="ml-auto"
                          :style="{ color: 'var(--primary-deep)', fontWeight: 600 }"
                        >自家</span>
                      </div>
                    </div>
                  </div>
                </template>
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
                  暂无快照数据 —— 跑一次「立刻监测」，下方将列出当前榜上的前 N 个答案，命中目标品牌的会高亮。
                </div>
              </div>
            </template>
          </template>
        </section>
      </div>
    </template>

    <!-- ── 平台评论 ─────────────────────────────────────────────── -->
    <template v-else-if="activeTab === 'comment'">
      <!-- alert hero (stacked when commentAlerts.length > 1) -->
      <div
        v-if="commentAlerts.length > 0 && currentCommentAlert"
        class="relative flex-shrink-0"
        :style="{ paddingBottom: commentAlerts.length > 1 ? '14px' : '0' }"
      >
        <div
          v-if="commentAlerts.length > 1"
          aria-hidden="true"
          :style="{
            position: 'absolute',
            left: '8px',
            right: '8px',
            top: '8px',
            bottom: '0',
            background: 'var(--dark)',
            opacity: 0.55,
            borderRadius: 'var(--radius-card)',
            zIndex: 0,
          }"
        />
        <div
          v-if="commentAlerts.length > 2"
          aria-hidden="true"
          :style="{
            position: 'absolute',
            left: '16px',
            right: '16px',
            top: '14px',
            bottom: '-6px',
            background: 'var(--dark)',
            opacity: 0.3,
            borderRadius: 'var(--radius-card)',
            zIndex: 0,
          }"
        />
      <div
        class="relative overflow-hidden"
        :style="{
          background: 'var(--dark)',
          color: '#fbf7ec',
          borderRadius: 'var(--radius-card)',
          padding: '26px 28px',
          zIndex: 1,
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
              <span>{{ commentAlerts.length }} 个紧急告警 · B 站</span>
              <span
                v-if="commentAlerts.length > 1"
                :style="{ color: 'rgba(255,255,255,0.4)', letterSpacing: '0' }"
              >· {{ commentAlertIdx + 1 }} / {{ commentAlerts.length }}</span>
            </div>
            <div
              class="font-display mt-2 font-bold"
              :style="{ fontSize: '28px', letterSpacing: '-0.5px', lineHeight: '1.25' }"
            >
              「{{ currentCommentAlert.keyword }}」<br />
              <span :style="{ color: 'var(--primary)' }">{{ currentCommentAlert.headline }}</span>
            </div>
            <div class="mt-2 text-[12.5px]" :style="{ color: 'rgba(255,255,255,0.6)' }">
              {{ currentCommentAlert.subtitle }}
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <template v-if="commentAlerts.length > 1">
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
                @click="cycleAlert('comment', -1)"
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
                @click="cycleAlert('comment', 1)"
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
              @click="openCommentAlert(currentCommentAlert)"
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
              @click="onAlertAction('repost')"
            >
              <Icon name="refresh" :size="14" />
              <span>补发评论</span>
            </button>
          </div>
        </div>
      </div>
      </div><!-- /alert hero stack wrapper -->

      <!-- platform sub-pivot -->
      <div class="flex flex-shrink-0 items-center justify-between">
        <div
          class="flex items-center"
          :style="{
            background: 'var(--card)',
            borderRadius: '999px',
            padding: '4px',
            border: '1px solid var(--line)',
          }"
        >
          <button
            v-for="p in PLATFORMS"
            :key="p.k"
            type="button"
            class="inline-flex items-center"
            :style="{
              height: '32px',
              padding: '0 16px',
              borderRadius: '999px',
              background: commentSubtab === p.k ? 'var(--dark)' : 'transparent',
              color: commentSubtab === p.k ? '#fbf7ec' : 'var(--ink-3)',
              fontSize: '12.5px',
              fontWeight: 500,
              gap: '8px',
              transition: 'background .15s, color .15s',
            }"
            @click="commentSubtab = p.k"
          >
            <span
              :style="{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: p.color,
                boxShadow: commentSubtab === p.k ? '0 0 0 2px rgba(255,255,255,0.15)' : 'none',
              }"
            />
            <span>{{ p.l }}</span>
          </button>
        </div>
        <!--
          评论平台只保留批量导入：每天要监测的视频链接通常很多，
          一条一条用 modal 加效率太低。单条的「新增任务」按钮在评论
          tab 下隐藏，统一走批量入口（用户决定）。Cookie 仍保留。
        -->
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
            @click="showCookieMgr = true"
          >
            <Icon name="key" :size="12" />
            <span>Cookie</span>
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
            :style="{
              background: 'var(--primary)',
              color: '#fff',
              borderRadius: '999px',
            }"
            @click="showBatchImport = true"
          >
            <Icon name="folder" :size="12" />
            <span>批量导入</span>
          </button>
        </div>
      </div>

      <!-- comment platform body -->
      <!--
        空态：示例已清 & 没真实任务 ⇒ commentRows 必为空。统一一个分支
        覆盖 demo 空态 + 真实空态，文案不变。
      -->
      <template v-if="commentRows.length === 0">
        <div
          class="flex min-h-0 flex-1 flex-col items-center justify-center text-center"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '60px 30px',
          }"
        >
          <span
            class="inline-flex items-center justify-center"
            :style="{
              width: '54px',
              height: '54px',
              borderRadius: '16px',
              background: 'var(--card-2)',
              color: 'var(--ink-3)',
            }"
          >
            <Icon name="radar" :size="22" />
          </span>
          <div
            class="font-display mt-4 font-bold"
            :style="{ fontSize: '18px' }"
          >
            {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 还没有监测任务
          </div>
          <div
            class="mt-1.5 max-w-[400px] text-[12.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            把 {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 上要监控的视频/帖子链接加进来，CSM 会定时抓取评论留存情况。
          </div>
          <button
            type="button"
            class="mt-5 inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium"
            :style="{
              background: 'var(--primary)',
              color: '#fff',
              borderRadius: '999px',
            }"
            @click="showAddTask = true"
          >
            <Icon name="plus" :size="14" />
            <span>添加 {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 监控</span>
          </button>
        </div>
      </template>

      <!--
        rich 三栏视图 —— demoMode 和真实数据共用同一段模板，数据来自
        commentRows / videosByBatchId / retentionPoints / deletedComments。
      -->
      <template v-else>
        <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
          <!-- ── 左列：一级 任务列表 / 二级 视频列表 ─────────────── -->
          <section
            class="flex h-full flex-col"
            :style="{
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-card)',
              padding: '22px',
            }"
          >
            <!-- L1 任务列表 -->
            <template v-if="!selectedCommentTaskId">
              <div class="mb-3 flex-shrink-0">
                <div class="font-display text-[14px] font-semibold">
                  {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} · 评论监控
                </div>
                <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                  评论留存率 = 当前可见数 / 历史峰值
                </div>
              </div>
              <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
                <div
                  class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
                  :style="{
                    gridTemplateColumns: '1.6fr .7fr .7fr 1fr',
                    letterSpacing: '1.2px',
                    color: 'var(--ink-3)',
                    borderBottom: '1px solid var(--line)',
                  }"
                >
                  <div>任务名字</div><div>留存</div><div>变化</div><div>状态 / 操作</div>
                </div>
                <div
                  v-for="(t, i) in commentRows"
                  :key="t.id"
                  class="grid cursor-pointer items-center transition"
                  :style="{
                    gridTemplateColumns: '1.6fr .7fr .7fr 1fr',
                    borderBottom: i < commentRows.length - 1 ? '1px solid var(--line)' : 'none',
                    padding: '14px 8px',
                    borderRadius: '10px',
                  }"
                  @click="openCommentDetail(t.id)"
                  @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
                  @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                >
                  <div class="min-w-0">
                    <div
                      class="truncate text-[13px] font-medium"
                      :style="{ color: 'var(--primary-deep)' }"
                    >{{ t.kw }}</div>
                    <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                      {{ t.lastChecked }} · {{ (videosByBatchId[t.id] ?? []).length }} 条视频
                    </div>
                  </div>
                  <div>
                    <div class="font-display text-[13px] font-bold">
                      {{ t.retained }}/{{ t.total }}
                    </div>
                    <div
                      :style="{
                        height: '3px',
                        background: 'var(--line)',
                        borderRadius: '999px',
                        marginTop: '4px',
                        width: '60px',
                      }"
                    >
                      <div
                        :style="{
                          width: `${(t.retained / t.total) * 100}%`,
                          height: '100%',
                          background: t.retained < t.total ? 'var(--red, #d85a48)' : 'var(--green, #6c9b5d)',
                          borderRadius: '999px',
                        }"
                      />
                    </div>
                  </div>
                  <div>
                    <Pill v-if="t.delta < 0" tone="alert">
                      <Icon name="arrowDown" :size="10" />{{ t.delta }}
                    </Pill>
                    <Pill v-else-if="t.delta > 0" tone="ok">
                      <Icon name="arrowUp" :size="10" />+{{ t.delta }}
                    </Pill>
                    <Pill v-else tone="info">持平</Pill>
                  </div>
                  <!--
                    状态 pill 文字避开"删除"二字 —— 跟右边的 🗑 删除按钮
                    撞义会被误读为"删除按钮 + 删除按钮"。改用"评论丢失"
                    更清楚反映留存率低的含义；编辑/删除按钮跟 pill 之间
                    留 ml-auto 拉开间距。
                  -->
                  <div class="flex items-center gap-2">
                    <Pill v-if="t.status === 'ok'" tone="ok">正常</Pill>
                    <Pill v-else-if="t.status === 'warn'" tone="warn">关注</Pill>
                    <Pill v-else tone="alert">评论丢失</Pill>
                    <!--
                      批量「立刻监测」—— 一次派发该批次下所有子任务。``ml-auto``
                      挂在它身上，把它和后面的 edit/delete 按钮组一起推到行尾，
                      跟 pill 之间留空白。文案/disabled 从 batchRunState 拿，
                      跑起来后随 SSE finished 事件递进显示进度 N/M。
                    -->
                    <button
                      v-if="!demoMode"
                      type="button"
                      class="ml-auto whitespace-nowrap text-[11px]"
                      :style="{
                        padding: '4px 10px',
                        borderRadius: '999px',
                        color: batchRunState(t.id).disabled ? 'var(--ink-3)' : 'var(--primary-deep)',
                        cursor: batchRunState(t.id).disabled ? 'not-allowed' : 'pointer',
                      }"
                      :disabled="batchRunState(t.id).disabled"
                      :title="`批量派发该批次下所有视频任务（共 ${tasks.filter((x) => parseBatchName(x.name) === t.id).length} 条）`"
                      @click.stop="runBatch(t.id)"
                    >{{ batchRunState(t.id).label }}</button>
                    <div v-if="!demoMode" class="flex flex-shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        class="inline-flex h-7 w-7 items-center justify-center"
                        :style="{
                          borderRadius: '999px',
                          color: 'var(--ink-3)',
                        }"
                        title="编辑批次（重命名 / Top-N / 品牌关键词，应用到全部子任务）"
                        @click.stop="openEditBatch(t.id)"
                      >
                        <Icon name="edit" :size="13" />
                      </button>
                      <button
                        type="button"
                        class="inline-flex h-7 w-7 items-center justify-center"
                        :style="{
                          borderRadius: '999px',
                          color: 'var(--ink-3)',
                        }"
                        title="删除批次（包括所有子任务）"
                        @click.stop="deleteBatch(t.id)"
                      >
                        <Icon name="trash" :size="13" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <!-- L2 视频列表（点任务名进来） -->
            <template v-else>
              <div class="mb-3 flex flex-shrink-0 items-center gap-3">
                <button
                  type="button"
                  class="inline-flex flex-shrink-0 items-center justify-center"
                  :style="{
                    width: '28px',
                    height: '28px',
                    borderRadius: '999px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                    color: 'var(--ink-2)',
                  }"
                  title="返回任务列表"
                  @click="backToCommentList"
                >
                  <Icon name="arrowLeft" :size="13" />
                </button>
                <div class="min-w-0">
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} · 视频列表
                  </div>
                  <div class="font-display truncate text-[14px] font-semibold">
                    {{ selectedCommentRow?.kw }}
                  </div>
                </div>
                <span
                  class="ml-auto flex-shrink-0 rounded-full text-[10.5px]"
                  :style="{
                    background: 'var(--card-2)',
                    color: 'var(--ink-3)',
                    padding: '2px 8px',
                  }"
                >{{ selectedTaskVideos.length }} 条</span>
              </div>
              <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
                <div
                  class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
                  :style="{
                    gridTemplateColumns: '1.8fr .6fr .6fr',
                    letterSpacing: '1.2px',
                    color: 'var(--ink-3)',
                    borderBottom: '1px solid var(--line)',
                  }"
                >
                  <div>视频名字</div><div>评论排名</div><div>状态</div>
                </div>
                <div
                  v-for="(v, i) in selectedTaskVideos"
                  :key="v.id"
                  class="grid cursor-pointer items-center transition"
                  :style="{
                    gridTemplateColumns: '1.8fr .6fr .6fr',
                    borderBottom: i < selectedTaskVideos.length - 1 ? '1px solid var(--line)' : 'none',
                    padding: '14px 8px',
                    borderRadius: '10px',
                    background: selectedVideoId === v.id ? 'var(--card-2)' : 'transparent',
                  }"
                  @click="selectVideo(v.id)"
                  @mouseenter="(e) => { if (selectedVideoId !== v.id) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                  @mouseleave="(e) => { if (selectedVideoId !== v.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
                >
                  <div class="min-w-0">
                    <div
                      class="text-[13px] font-medium"
                      :title="v.title"
                      :style="{
                        color: selectedVideoId === v.id ? 'var(--primary-deep)' : 'var(--ink)',
                      }"
                    >{{ truncate15(v.title) }}</div>
                    <div class="mt-0.5 truncate text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                      {{ v.postedAt }}
                    </div>
                  </div>
                  <div>
                    <!-- rank=0 (即 backend rank=-1) = 未在前 scrape_top_n 条命中，显示 "无" 与右侧 "未找到" pill 语义对齐 -->
                    <span
                      v-if="v.rank > 0"
                      class="font-display text-[14px] font-bold"
                      :style="{ color: v.status === 'ok' ? 'var(--ink)' : 'var(--red, #d85a48)' }"
                    >#{{ v.rank }}</span>
                    <span
                      v-else
                      class="text-[11.5px]"
                      :style="{ color: 'var(--red, #d85a48)' }"
                    >无</span>
                  </div>
                  <div>
                    <Pill v-if="v.status === 'ok'" tone="ok">在显</Pill>
                    <Pill v-else-if="v.status === 'folded'" tone="warn">跌出理想</Pill>
                    <Pill v-else tone="alert">未找到</Pill>
                  </div>
                </div>
              </div>
            </template>
          </section>

          <!-- ── 右列：未选视频 → 留存汇总；已选视频 → 单视频详情 ── -->
          <section
            class="flex h-full flex-col overflow-y-auto"
            :style="{
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-card)',
              padding: '22px',
            }"
          >
            <!-- L3 单视频详情（点视频名后右列变这个） -->
            <template v-if="selectedVideo">
              <div class="mb-3 flex flex-shrink-0 items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                    <template v-if="selectedVideo.rank > 0">视频 #{{ selectedVideo.rank }} 详情</template>
                    <template v-else>视频详情（评论未找到）</template>
                  </div>
                  <div
                    class="font-display mt-0.5 font-bold"
                    :title="selectedVideo.title"
                    :style="{ fontSize: '15px', lineHeight: 1.35 }"
                  >{{ selectedVideo.title }}</div>
                </div>
                <button
                  type="button"
                  class="inline-flex flex-shrink-0 items-center justify-center"
                  :style="{
                    width: '26px',
                    height: '26px',
                    borderRadius: '999px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                    color: 'var(--ink-2)',
                  }"
                  title="关闭详情"
                  @click="closeVideoDetail"
                >
                  <Icon name="x" :size="13" />
                </button>
              </div>

              <!-- 状态 / 排名 KPI -->
              <div class="mb-4 mt-3 grid grid-cols-3 gap-2 flex-shrink-0">
                <div
                  :style="{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">评论排名</div>
                  <div
                    class="font-display mt-0.5 font-bold"
                    :style="{
                      fontSize: '18px',
                      color: selectedVideo.rank > 0
                        ? (selectedVideo.status === 'ok' ? 'var(--ink)' : 'var(--red, #d85a48)')
                        : 'var(--red, #d85a48)',
                    }"
                  >
                    <template v-if="selectedVideo.rank > 0">#{{ selectedVideo.rank }}</template>
                    <span v-else :style="{ fontSize: '14px' }">无</span>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">状态</div>
                  <div class="mt-1.5">
                    <Pill v-if="selectedVideo.status === 'ok'" tone="ok">在显</Pill>
                    <Pill v-else-if="selectedVideo.status === 'folded'" tone="warn">跌出理想</Pill>
                    <Pill v-else tone="alert">未找到</Pill>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">总评论数</div>
                  <div
                    class="font-display mt-0.5 font-bold"
                    :style="{ fontSize: '18px' }"
                  >{{ selectedVideo.totalComments }}</div>
                </div>
              </div>

              <!-- 我的评论原文 -->
              <div class="mb-2 text-[12px] font-semibold flex-shrink-0">我的评论</div>
              <div
                class="flex-shrink-0"
                :style="{
                  padding: '12px 14px',
                  borderRadius: '10px',
                  background:
                    selectedVideo.status === 'deleted'
                      ? 'rgba(216,90,72,0.07)'
                      : selectedVideo.status === 'folded'
                        ? 'rgba(245,192,66,0.08)'
                        : 'var(--card-2)',
                  border: '1px solid var(--line)',
                  fontSize: '12.5px',
                  lineHeight: 1.6,
                  color: 'var(--ink)',
                }"
              >「{{ selectedVideo.myComment }}」</div>
              <div class="mt-1 flex-shrink-0 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                发布于 {{ selectedVideo.postedAt }}
              </div>

              <!-- 操作按钮 —— 真实数据下额外挂一个"立刻跑"，复用 zhihu 同款 SSE 触发流 -->
              <div class="mt-5 flex flex-shrink-0 gap-2">
                <a
                  :href="selectedVideo.url"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px]"
                  :style="{
                    background: 'transparent',
                    color: 'var(--ink-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '999px',
                    textDecoration: 'none',
                  }"
                >
                  <Icon name="external" :size="13" />
                  <span>打开视频</span>
                </a>
                <button
                  v-if="realTaskIdFromVideoId(selectedVideo.id)"
                  type="button"
                  class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px]"
                  :style="{
                    background: 'transparent',
                    color: runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]
                      ? 'var(--ink-3)'
                      : 'var(--primary-deep)',
                    border: '1px solid ' + (runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]
                      ? 'var(--line)'
                      : 'rgba(238,106,42,0.3)'),
                    borderRadius: '999px',
                    cursor: runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0] ? 'not-allowed' : 'pointer',
                  }"
                  :disabled="!!runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]"
                  @click="() => { const id = realTaskIdFromVideoId(selectedVideo!.id); if (id) runNow(id); }"
                >
                  <Spinner
                    v-if="runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]"
                    :size="13"
                  />
                  <Icon v-else name="refresh" :size="13" />
                  <span>{{ runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0] ? "监测中…" : "立刻监测" }}</span>
                </button>
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px] font-medium"
                  :style="{
                    background: 'var(--primary)',
                    color: '#fff',
                    borderRadius: '999px',
                  }"
                  @click="onAlertAction('repost')"
                >
                  <Icon name="refresh" :size="13" />
                  <span>补发评论</span>
                </button>
              </div>
            </template>

            <!-- L1/L2 默认右列 —— 留存趋势 + 被删评论 -->
            <template v-else>
              <div class="flex-shrink-0">
                <div class="font-display text-[14px] font-semibold">
                  {{ selectedCommentTaskId ? "任务汇总" : "留存趋势" }}
                </div>
                <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                  {{ selectedCommentTaskId ? "点左侧视频名查看单条评论详情" : "近 7 天" }}
                </div>
              </div>
              <div class="mt-3">
                <!--
                  真实数据 sparkline 暂时只有 prev/latest 两点（来自 limit=2
                  的快照对）；点不够时 Sparkline 自己会 fallback 到空态。
                  后续要更细，可在选中批次时再拉每个 task limit=14 聚合。
                -->
                <Sparkline
                  v-if="retentionPoints.length >= 2"
                  :points="retentionPoints"
                  :width="360"
                  :height="80"
                  stroke="var(--red, #d85a48)"
                  :axis-labels="COMMENT_SPARK_LABELS"
                  fluid
                />
                <div
                  v-else
                  class="text-[11.5px]"
                  :style="{ color: 'var(--ink-3)', padding: '6px 0' }"
                >
                  暂无足够的历史快照画趋势 —— 至少需要两次检查后才能成线。
                </div>
              </div>
              <div class="mt-4">
                <div class="mb-2 text-[12px] font-semibold">
                  {{
                    deletedComments.length
                      ? `被删的 ${deletedComments.length} 条评论`
                      : '暂无被删评论'
                  }}
                </div>
                <div
                  v-for="(x, i) in deletedComments"
                  :key="i"
                  class="mb-1 flex items-center gap-3"
                  :style="{
                    padding: '10px',
                    borderRadius: '10px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <Pill :tone="x.tone">{{ x.tag }}</Pill>
                  <span class="flex-1 text-[12px]">{{ x.who }}</span>
                  <span class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">{{ x.date }}</span>
                </div>
              </div>

              <!--
                只有进入 L2（选中任务但还没选视频）才显示启停 + 频率
                控件 —— 在 L1 这里 selectedCommentTaskId 为空，没有具体
                任务可以挂这两个状态，控件就藏起来。
              -->
              <div
                v-if="selectedCommentTaskId"
                class="mt-4 flex items-center gap-2"
                :style="{
                  paddingTop: '14px',
                  borderTop: '1px solid var(--line)',
                }"
              >
                <button
                  type="button"
                  class="inline-flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-[12px] font-medium"
                  :style="{
                    background: ensureCommentState(selectedCommentTaskId).enabled ? 'var(--card-2)' : 'var(--primary)',
                    color: ensureCommentState(selectedCommentTaskId).enabled ? 'var(--ink)' : '#fff',
                    border: '1px solid ' + (ensureCommentState(selectedCommentTaskId).enabled ? 'var(--line)' : 'var(--primary)'),
                    borderRadius: '999px',
                  }"
                  :title="ensureCommentState(selectedCommentTaskId).enabled ? '点击暂停监测' : '点击启动监测'"
                  @click="toggleMonitor('comment', selectedCommentTaskId)"
                >
                  <Icon
                    :name="ensureCommentState(selectedCommentTaskId).enabled ? 'check' : 'play'"
                    :size="13"
                  />
                  <span>
                    {{ ensureCommentState(selectedCommentTaskId).enabled ? '监测进行中' : '启动监测' }}
                  </span>
                </button>
                <div class="flex flex-1 items-center gap-2">
                  <Icon
                    name="calendar"
                    :size="13"
                    :style="{ color: 'var(--ink-3)' }"
                  />
                  <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">监测定时</span>
                  <FormSelect
                    :model-value="ensureCommentState(selectedCommentTaskId).schedule"
                    :options="SCHEDULE_OPTIONS"
                    width="140"
                    @update:model-value="(v) => changeSchedule('comment', selectedCommentTaskId!, String(v))"
                  />
                </div>
              </div>
            </template>
          </section>
        </div>
      </template>

      <!--
        以前真实数据走的是一段 flat fallback list（只显任务名 + 状态 pill），
        现在 rich 三栏视图既适配 demo 也适配真实，所以这个 fallback 整段删
        掉。L3 单视频详情里需要的"立刻跑 / 状态 spinner"已经接到了选中
        任务，详见 selectedVideo + selectedRealTaskId 流。
      -->
    </template>

    <!-- ── 百度关键词（顶级 tab，渲染同款 BaiduRankingPage）────────── -->
    <template v-else-if="activeTab === 'baidu'">
      <BaiduRankingPage
        @add-task="showAddTask = true"
        @batch-import="showBatchImport = true"
        @edit-task="(t) => { editingTask = t as any; showAddTask = true; }"
      />
    </template>

    <!-- ── 历史报告（重构后：sub-pivot + 两个子页）──────────────────── -->
    <template v-else>
      <section
        class="flex min-h-0 flex-1 flex-col"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <!-- sub-pivot：评论留存率 / 知乎排名 -->
        <div class="mb-3 flex-shrink-0 flex justify-between items-center">
          <div>
            <div class="font-display text-[14px] font-semibold">历史监测报告</div>
            <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              按业务拆分：评论平台留存率 / 知乎品牌排名分析
            </div>
          </div>
          <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }">
            <button
              @click="historySubtab = 'retention'"
              class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
              :style="{
                background: historySubtab === 'retention' ? 'var(--dark)' : 'transparent',
                color: historySubtab === 'retention' ? 'var(--card)' : 'var(--ink-3)',
              }"
            >评论留存率</button>
            <button
              @click="historySubtab = 'zhihu'"
              class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
              :style="{
                background: historySubtab === 'zhihu' ? 'var(--dark)' : 'transparent',
                color: historySubtab === 'zhihu' ? 'var(--card)' : 'var(--ink-3)',
              }"
            >知乎排名</button>
            <button
              @click="historySubtab = 'baidu'"
              class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
              :style="{
                background: historySubtab === 'baidu' ? 'var(--dark)' : 'transparent',
                color: historySubtab === 'baidu' ? 'var(--card)' : 'var(--ink-3)',
              }"
            >百度排名</button>
          </div>
        </div>

        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <RetentionPage v-if="historySubtab === 'retention'" @navigate="goToCommentTask" />
          <ZhihuRankingPage v-else-if="historySubtab === 'zhihu'" @navigate="goToZhihuTask" />
          <BaiduSEOAnalytics v-else-if="historySubtab === 'baidu'" @navigate="goToBaiduTask" />
        </div>
      </section>
    </template>

    <!-- ── Modals ──────────────────────────────────────────────── -->
    <AddTaskModal
      :open="showAddTask"
      :editing-task="editingTask as any"
      :default-type="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : activeTab === 'baidu' || (activeTab === 'report' && historySubtab === 'baidu')
            ? 'baidu_keyword'
            : commentSubtab === 'bilibili'
              ? 'bilibili_comment'
              : commentSubtab === 'douyin'
                ? 'douyin_comment'
                : 'kuaishou_comment'
      "
      @update:open="(v) => { showAddTask = v; clearEditOnClose(); }"
      @created="onTaskMutatedReload"
      @updated="onTaskMutatedReload"
    />
    <EditBatchModal
      v-model:open="showEditBatch"
      :batch-name="editingBatchName"
      :tasks="editingBatchTasks as any"
      @updated="onTaskMutatedReload"
    />
    <BatchImportTaskModal
      v-model:open="showBatchImport"
      :default-type="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : activeTab === 'baidu' || (activeTab === 'report' && historySubtab === 'baidu')
            ? 'baidu_keyword'
            : commentSubtab === 'bilibili'
              ? 'bilibili_comment'
              : commentSubtab === 'douyin'
                ? 'douyin_comment'
                : 'kuaishou_comment'
      "
      @imported="loadTasks(activeTab === 'zhihu' ? 'zhihu_question' : PLATFORM_TYPE[commentSubtab])"
    />
    <CookieManagerModal
      v-model:open="showCookieMgr"
      :default-platform="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : commentSubtab === 'bilibili'
            ? 'bilibili_comment'
            : commentSubtab === 'douyin'
              ? 'douyin_comment'
              : 'kuaishou_comment'
      "
    />
    <AlertDetailModal
      v-model:open="showAlertModal"
      :kind="alertKind"
      :zhihu-data="zhihuAlertData ?? undefined"
      :comment-data="commentAlertData ?? undefined"
      @action="onAlertAction"
    />
  </div>
</template>
