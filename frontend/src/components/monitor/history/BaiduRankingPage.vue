<script setup lang="ts">
/**
 * 百度关键词工作台 —— 与知乎问题工作台同款双卡布局。
 * 左：富任务表（搜索关键词 / 上次 / 变化 / 状态 / 操作）
 * 右：3 KPI + sparkline + 每关键词折叠结果段
 */
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { subscribe } from "@/api/client";
import Sparkline from "@/components/ui/Sparkline.vue";
import Pill from "@/components/ui/Pill.vue";
import Icon from "@/components/ui/Icon.vue";

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
const { whenReady } = useSidecarReady();
const toast = useToast();

// ──────────────────────────── state ────────────────────────────

const tasks = ref<TaskItem[]>([]);
const selectedId = ref<number | null>(null);
// Selected keyword index in Level 2 (for the per-keyword ranking detail panel)
const selectedKeywordIdx = ref<number | null>(null);
const history = ref<ResultItem[]>([]);
const loadingTasks = ref(false);
const loadingHistory = ref(false);
const runningNow = ref(false);
// Level 1 右卡用：鼠标悬停哪个任务行 → 右卡显示那个任务的属性预览
const hoveredId = ref<number | null>(null);
// Set of task IDs currently being fetched (driven by SSE started/finished
// + optimistic local mark when user clicks 立刻监测).
const runningTaskIds = ref<Set<number>>(new Set());

function isRunning(taskId: number): boolean {
  return runningTaskIds.value.has(taskId);
}

function markRunning(taskId: number): void {
  const s = new Set(runningTaskIds.value);
  s.add(taskId);
  runningTaskIds.value = s;
}

function clearRunning(taskId: number): void {
  if (!runningTaskIds.value.has(taskId)) return;
  const s = new Set(runningTaskIds.value);
  s.delete(taskId);
  runningTaskIds.value = s;
}

// ──────────────────────────── derived ────────────────────────────

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedId.value) ?? null,
);

// Level 1 右卡预览：优先 hover 的任务，没 hover 时 fallback 到第一个任务
const previewTask = computed<TaskItem | null>(() => {
  if (hoveredId.value !== null) {
    return tasks.value.find((t) => t.id === hoveredId.value) ?? null;
  }
  return tasks.value[0] ?? null;
});

const latestResult = computed(() =>
  history.value.length > 0 ? history.value[0] : null,
);

const latestMetric = computed<BaiduMetric | null>(
  () => latestResult.value?.metric ?? null,
);

const prevMetric = computed<BaiduMetric | null>(
  () => (history.value.length > 1 ? history.value[1]?.metric ?? null : null),
);

// Trend chart: history is newest-first from API; reverse for chronological
const chronoHistory = computed(() => [...history.value].reverse());

// Sparkline: matched_keywords over last 14 results (kept for potential future use)
const _sparkPoints = computed<number[]>(() =>
  chronoHistory.value
    .slice(-14)
    .map((r) => r.metric?.matched_keywords ?? 0),
);
void _sparkPoints; // suppress unused warning

const sparkLabels = computed<string[]>(() => {
  const slice = chronoHistory.value.slice(-14);
  if (slice.length <= 6) return slice.map((r) => r.checked_at.slice(5, 10));
  const step = Math.floor(slice.length / 3);
  return [0, step, step * 2, slice.length - 1].map(
    (i) => slice[Math.min(i, slice.length - 1)].checked_at.slice(5, 10),
  );
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

const placedCountPrev = computed<number>(() => {
  if (!prevMetric.value) return 0;
  return prevMetric.value.keywords.filter(
    (kw) => kw.default_first_rank > 0 && kw.default_first_rank <= idealRank.value,
  ).length;
});
void placedCountPrev; // suppress unused warning

// 最新资讯卡位数量: across all keywords with news_present, count matches in news_results
// Returns null if NO keyword has news_present (display as "无")
const newsPlacedCount = computed<number | null>(() => {
  if (!latestMetric.value) return null;
  const newsKws = latestMetric.value.keywords.filter((kw) => kw.news_present);
  if (newsKws.length === 0) return null;
  return newsKws.reduce((sum, kw) => {
    return sum + kw.news_results.filter((r) => r.matches_brand).length;
  }, 0);
});

// 状态 pill tone + label based on current vs total
const placementStatus = computed<{ label: string; tone: PillTone }>(() => {
  const m = latestMetric.value;
  if (!m) return { label: "未跑", tone: "info" };
  if (m.captcha_hit) return { label: "验证码", tone: "warn" };
  const placed = placedCountCurrent.value;
  const total = m.total_keywords || 1;
  if (placed === total && total > 0) return { label: "全部卡位", tone: "ok" };
  if (placed > 0) return { label: `部分卡位 (${placed}/${total})`, tone: "warn" };
  return { label: "未卡位", tone: "alert" };
});

// Sparkline: 卡位 count (not matched_keywords) over last 14 days
const sparkPointsPlaced = computed<number[]>(() =>
  chronoHistory.value.slice(-14).map((r) => {
    if (!r.metric) return 0;
    return r.metric.keywords.filter(
      (kw) => kw.default_first_rank > 0 && kw.default_first_rank <= idealRank.value,
    ).length;
  }),
);

// Currently selected keyword's details for the right panel detail section
const currentKeyword = computed<BaiduPerKeyword | null>(() => {
  if (!latestMetric.value || selectedKeywordIdx.value === null) return null;
  return latestMetric.value.keywords[selectedKeywordIdx.value] ?? null;
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

interface TaskRowState {
  statusLabel: string;
  tone: PillTone;
}

function taskRowState(task: TaskItem): TaskRowState {
  const s = task.last_status;
  if (!task.last_check_at || !s) return { statusLabel: "未跑", tone: "info" };
  if (s === "captcha") return { statusLabel: "验证码", tone: "warn" };
  if (s === "error" || s === "fail") return { statusLabel: "失败", tone: "alert" };
  if (s === "ok") {
    if (task.id === selectedId.value) {
      const m = latestMetric.value;
      if (!m) return { statusLabel: "未跑", tone: "info" };
      if (m.captcha_hit) return { statusLabel: "验证码", tone: "warn" };
      if (m.matched_keywords > 0) return { statusLabel: "上榜", tone: "ok" };
      return { statusLabel: "未命中", tone: "warn" };
    }
    return { statusLabel: "正常", tone: "ok" };
  }
  return { statusLabel: s, tone: "info" };
}

function scheduleLabel(cron?: string): string {
  if (!cron || cron === "manual") return "手动";
  return cron;
}

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
    // Do NOT auto-select: Level 1 (task list) is the default landing.
  } catch (e: any) {
    toast.error(`加载任务列表失败: ${e?.message ?? e}`);
  } finally {
    loadingTasks.value = false;
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

async function runNow() {
  if (!selectedId.value || runningNow.value) return;
  runningNow.value = true;
  markRunning(selectedId.value);
  try {
    await whenReady();
    await sidecar.client.post(`/api/monitor/tasks/${selectedId.value}/run-now`);
    toast.info("已派发，结果会通过 SSE 流推回");
  } catch (e: any) {
    if (selectedId.value !== null) clearRunning(selectedId.value);
    toast.error(`派发失败: ${e?.message ?? e}`);
  } finally {
    runningNow.value = false;
  }
}

async function runNowTask(id: number) {
  if (id !== selectedId.value) {
    selectedId.value = id;
  }
  runNow();
}

async function deleteTask(task: TaskItem) {
  if (!confirm(`确认删除任务「${task.name}」？此操作不可恢复。`)) return;
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

function backToList(): void {
  selectedId.value = null;
  selectedKeywordIdx.value = null;
}

// ──────────────────────────── lifecycle ────────────────────────────

// ──────────────────────────── SSE bus ────────────────────────────
// Listen to monitor events so the row shows 「监测中…」 spinner while a
// task is actually fetching, and clears + reloads history on finish.

let stopSse: (() => void) | null = null;

function startSse(): void {
  stopSse = subscribe("/api/monitor/events", {
    started: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) markRunning(d.task_id);
    },
    finished: (d: any) => {
      if (typeof d.task_id !== "number") return;
      clearRunning(d.task_id);
      // Find the task in our list, refresh its last_check_at/last_status
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) {
        t.last_check_at = d.at ?? t.last_check_at;
        t.last_status = d.result?.status ?? t.last_status;
      }
      // If it's the selected task, reload its history so the detail card
      // refreshes immediately.
      if (selectedId.value === d.task_id) {
        loadHistory(d.task_id);
      }
    },
    failed: (d: any) => {
      if (typeof d.task_id !== "number") return;
      clearRunning(d.task_id);
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) t.last_status = "failed";
    },
  });
}

onMounted(() => {
  loadTasks();
  startSse();
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
                百度搜索 · 关键词排名监控
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
            <!-- Header row -->
            <div
              class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
              :style="{
                gridTemplateColumns: '1.6fr .7fr .5fr .5fr 1.4fr',
                letterSpacing: '1.2px',
                color: 'var(--ink-3)',
                borderBottom: '1px solid var(--line)',
              }"
            >
              <div>任务名字</div>
              <div>命中</div>
              <div>变化</div>
              <div>状态</div>
              <div>操作</div>
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
                  gridTemplateColumns: '1.6fr .7fr .5fr .5fr 1.4fr',
                  background: 'transparent',
                  borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
                  padding: '14px 8px',
                  borderRadius: '10px',
                }"
                @mouseenter="(e) => { hoveredId = t.id; (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                @click="selectedId = t.id"
              >
                <!-- 任务名字 + N关键词·品牌 -->
                <div class="min-w-0">
                  <div
                    class="truncate text-[13px] font-medium"
                    :style="{ color: 'var(--primary-deep)' }"
                  >{{ t.name }}</div>
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

                <!-- 命中：对于非当前选中任务无历史，一律"—" -->
                <div class="font-display text-[13px] font-bold" :style="{ color: 'var(--ink-3)' }">
                  —
                </div>

                <!-- 变化：无历史，一律"—" -->
                <div :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>

                <!-- 状态 -->
                <div>
                  <Pill v-if="isRunning(t.id)" tone="info">监测中…</Pill>
                  <Pill v-else :tone="taskRowState(t).tone">{{ taskRowState(t).statusLabel }}</Pill>
                </div>

                <!-- 操作 -->
                <div class="flex items-center gap-0.5">
                  <button
                    type="button"
                    class="whitespace-nowrap text-[11px]"
                    :disabled="isRunning(t.id)"
                    :style="{
                      padding: '4px 10px',
                      borderRadius: '999px',
                      color: 'var(--primary-deep)',
                      cursor: isRunning(t.id) ? 'not-allowed' : 'pointer',
                      opacity: isRunning(t.id) ? 0.5 : 1,
                    }"
                    @click.stop="runNowTask(t.id)"
                  >{{ isRunning(t.id) ? '监测中…' : '立刻监测' }}</button>
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

        <!-- ── 右卡：任务属性预览 ────────────────────────────────── -->
        <section
          class="flex min-h-0 flex-col overflow-y-auto"
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
                任务属性 · 点击行进入详情查看排名
              </div>
            </div>

            <!-- 属性表 -->
            <div class="flex flex-col gap-3 flex-shrink-0">
              <!-- 目标品牌 -->
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">目标品牌</div>
                <div class="text-[13px] font-medium">{{ previewTask.config.target_brand || '—' }}</div>
              </div>

              <!-- 搜索关键词列表 -->
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">
                  搜索关键词（{{ previewTask.config.search_keywords?.length ?? 0 }} 个）
                </div>
                <div class="flex flex-col gap-1">
                  <div
                    v-for="(kw, idx) in (previewTask.config.search_keywords ?? [])"
                    :key="idx"
                    class="text-[12.5px]"
                    :style="{
                      padding: '6px 10px',
                      background: 'var(--card-2)',
                      borderRadius: '6px',
                      borderLeft: '3px solid var(--primary)',
                    }"
                  >{{ kw }}</div>
                </div>
              </div>

              <!-- 检查频率 -->
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">检查频率</div>
                <div class="text-[12.5px]">{{ scheduleLabel(previewTask.schedule_cron) }}</div>
              </div>

              <!-- 上次检查 -->
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">上次检查</div>
                <div class="text-[12.5px]">
                  {{ previewTask.last_check_at ? previewTask.last_check_at.slice(0, 16).replace('T', ' ') : '从未' }}
                </div>
              </div>
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
          <!-- Card header with back button INSIDE (B站 style) -->
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
            <div class="min-w-0">
              <div class="text-[11px] uppercase" :style="{ color: 'var(--ink-3)', letterSpacing: '1.2px' }">
                百度排名 · 关键词列表
              </div>
              <div class="font-display text-[14px] font-semibold mt-0.5">
                {{ selectedTask?.name ?? '' }}
              </div>
              <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                {{ selectedTask?.config?.search_keywords?.length ?? 0 }} 个关键词
                <template v-if="selectedTask?.config?.target_brand">
                  · 品牌 {{ selectedTask.config.target_brand }}
                </template>
                · 检查频率 {{ scheduleLabel(selectedTask?.schedule_cron) }}
              </div>
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

            <!-- No history: 显示配置里的关键词列表，每条状态「未跑」 -->
            <template v-if="!latestMetric">
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
                <div>默认排名</div>
                <div>资讯排名</div>
                <div>状态</div>
              </div>
              <!-- 用 config.search_keywords 占位，但保持和有数据时一致的点击/选中行为 -->
              <div
                v-for="(kw, i) in (selectedTask?.config?.search_keywords ?? [])"
                :key="kw + '-noresult'"
                class="grid items-center cursor-pointer transition"
                :style="{
                  gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
                  borderBottom: i < (selectedTask?.config?.search_keywords?.length ?? 0) - 1 ? '1px solid var(--line)' : 'none',
                  padding: '12px 8px',
                  background: selectedKeywordIdx === i ? 'var(--card-2)' : 'transparent',
                }"
                @click="selectedKeywordIdx = i"
                @mouseenter="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                @mouseleave="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
              >
                <div class="min-w-0">
                  <div
                    class="truncate text-[12.5px] font-medium"
                    :style="{ color: selectedKeywordIdx === i ? 'var(--primary-deep)' : 'var(--ink)' }"
                  >{{ kw }}</div>
                </div>
                <div :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
                <div :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
                <div><Pill tone="info">未跑</Pill></div>
              </div>
              <div
                v-if="(selectedTask?.config?.search_keywords?.length ?? 0) === 0"
                class="py-10 text-center text-[12px]"
                :style="{ color: 'var(--ink-3)' }"
              >
                此任务未配置搜索关键词
              </div>
              <div
                v-else
                class="mt-3 px-2 text-[11px]"
                :style="{ color: 'var(--ink-3)' }"
              >
                暂无检查记录 — 点击右侧「▶ 启动监测」后会出排名数据。
              </div>
            </template>

            <template v-else>
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
                <div>默认排名</div>
                <div>资讯排名</div>
                <div>状态</div>
              </div>

              <!-- Keyword rows -->
              <div
                v-for="(kw, i) in latestMetric.keywords"
                :key="kw.keyword"
                class="grid items-center cursor-pointer transition"
                :style="{
                  gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
                  borderBottom: i < latestMetric.keywords.length - 1 ? '1px solid var(--line)' : 'none',
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
                    :style="{ color: selectedKeywordIdx === i ? 'var(--primary-deep)' : 'var(--ink)' }"
                  >{{ kw.keyword }}</div>
                </div>

                <!-- 默认排名 -->
                <div>
                  <div
                    class="font-display text-[13px] font-bold"
                    :style="{ color: kw.default_first_rank > 0 ? 'var(--primary-deep)' : 'var(--ink-3)' }"
                  >
                    {{ kw.default_first_rank > 0 ? `#${kw.default_first_rank}` : '—' }}
                  </div>
                  <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                    命中 {{ kw.default_matched_count }}/10
                  </div>
                </div>

                <!-- 资讯排名 -->
                <div>
                  <template v-if="kw.news_present">
                    <div
                      class="font-display text-[13px] font-bold"
                      :style="{ color: kw.news_first_rank > 0 ? '#4f7cff' : 'var(--ink-3)' }"
                    >
                      {{ kw.news_first_rank > 0 ? `#${kw.news_first_rank}` : '—' }}
                    </div>
                    <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                      命中 {{ kw.news_results.filter(r => r.matches_brand).length }}/{{ kw.news_results.length }}
                    </div>
                  </template>
                  <div v-else class="text-[11px]" :style="{ color: 'var(--ink-3)' }">无资讯</div>
                </div>

                <!-- 状态 -->
                <div>
                  <Pill v-if="kw.fetch_error" tone="alert">抓取失败</Pill>
                  <Pill v-else-if="kw.default_matched_count > 0 || (kw.news_present && kw.news_first_rank > 0)" tone="ok">上榜</Pill>
                  <Pill v-else tone="warn">未命中</Pill>
                </div>
              </div>
            </template>
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

          <!-- Loading -->
          <div
            v-if="loadingHistory"
            class="py-6 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            加载中…
          </div>

          <!-- KPI 三联 -->
          <div class="mb-4 grid flex-shrink-0 grid-cols-3 gap-3">
            <!-- KPI 1: 本次卡位数量 -->
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">本次卡位数量</div>
              <div class="font-display text-[20px] font-bold">{{ placedCountCurrent }}</div>
              <div class="text-[10.5px] mt-1" :style="{ color: 'var(--ink-3)' }">
                共 {{ latestMetric?.total_keywords ?? 0 }} 个关键词
              </div>
            </div>

            <!-- KPI 2: 状态 -->
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">状态</div>
              <div class="mt-1">
                <Pill :tone="placementStatus.tone">{{ placementStatus.label }}</Pill>
              </div>
              <div class="text-[10.5px] mt-2" :style="{ color: 'var(--ink-3)' }">
                理想排名：前 {{ idealRank }} 位
              </div>
            </div>

            <!-- KPI 3: 最新资讯卡位数量 -->
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">最新资讯卡位数量</div>
              <div class="font-display text-[20px] font-bold">
                {{ newsPlacedCount === null ? '无' : newsPlacedCount }}
              </div>
              <div class="text-[10.5px] mt-1" :style="{ color: 'var(--ink-3)' }">
                {{ newsPlacedCount === null ? '该轮无最新资讯' : '资讯区命中' }}
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

              <!-- 默认搜索 -->
              <div
                class="mb-3 rounded"
                :style="{ background: 'var(--card-2)', borderLeft: '3px solid var(--primary)', padding: '10px 12px' }"
              >
                <div class="text-[12px] font-semibold mb-2">
                  默认搜索
                  <span class="text-[11px] font-normal ml-1" :style="{ color: 'var(--ink-3)' }">
                    命中 {{ currentKeyword.default_matched_count }}/10
                  </span>
                </div>
                <div v-if="currentKeyword.default_results.length === 0" class="text-[11px] py-2" :style="{ color: 'var(--ink-3)' }">
                  无默认搜索结果
                </div>
                <div v-else class="flex flex-col gap-1">
                  <div
                    v-for="r in currentKeyword.default_results"
                    :key="r.url"
                    class="text-[11.5px] py-1.5 px-2 rounded"
                    :style="{
                      background: r.matches_brand ? 'rgba(238, 106, 42, 0.10)' : 'transparent',
                      border: r.matches_brand ? '1px solid rgba(238, 106, 42, 0.3)' : 'none',
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
                    <div class="text-[10.5px] mt-0.5 truncate" :style="{ color: 'var(--ink-3)' }">{{ r.host }}</div>
                  </div>
                </div>
              </div>

              <!-- 最新资讯 (only if news_present) -->
              <div
                v-if="currentKeyword.news_present"
                class="mb-3 rounded"
                :style="{ background: 'rgba(79, 124, 255, 0.06)', borderLeft: '3px solid #4f7cff', padding: '10px 12px' }"
              >
                <div class="text-[12px] font-semibold mb-2">
                  最新资讯
                  <span class="text-[11px] font-normal ml-1" :style="{ color: 'var(--ink-3)' }">
                    命中 {{ currentKeyword.news_results.filter(r => r.matches_brand).length }}/{{ currentKeyword.news_results.length }}
                  </span>
                </div>
                <div class="flex flex-col gap-1">
                  <div
                    v-for="r in currentKeyword.news_results"
                    :key="r.url"
                    class="text-[11.5px] py-1.5 px-2 rounded"
                    :style="{
                      background: r.matches_brand ? 'rgba(79, 124, 255, 0.12)' : 'transparent',
                      border: r.matches_brand ? '1px solid rgba(79, 124, 255, 0.3)' : 'none',
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
                    <div class="text-[10.5px] mt-0.5 truncate" :style="{ color: 'var(--ink-3)' }">{{ r.host }}</div>
                  </div>
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

  </div>
</template>
