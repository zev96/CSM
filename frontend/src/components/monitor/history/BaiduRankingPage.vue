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
const history = ref<ResultItem[]>([]);
const loadingTasks = ref(false);
const loadingHistory = ref(false);
const runningNow = ref(false);
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

// Sparkline: matched_keywords over last 14 results (replace 0 with 0, non-data stays 0)
const sparkPoints = computed<number[]>(() =>
  chronoHistory.value
    .slice(-14)
    .map((r) => r.metric?.matched_keywords ?? 0),
);

const sparkLabels = computed<string[]>(() => {
  const slice = chronoHistory.value.slice(-14);
  if (slice.length <= 6) return slice.map((r) => r.checked_at.slice(5, 10));
  const step = Math.floor(slice.length / 3);
  return [0, step, step * 2, slice.length - 1].map(
    (i) => slice[Math.min(i, slice.length - 1)].checked_at.slice(5, 10),
  );
});

// Delta: total_default_matches between current and previous
const matchesDelta = computed<number | null>(() => {
  const cur = latestMetric.value?.total_default_matches ?? null;
  const prv = prevMetric.value?.total_default_matches ?? null;
  if (cur === null || prv === null) return null;
  return cur - prv;
});

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

/** First keyword label with "(+N)" if more exist. */
function keywordSummary(cfg: TaskItem["config"]): string {
  const kws = cfg.search_keywords ?? [];
  if (kws.length === 0) return "—";
  const first = kws[0];
  if (kws.length === 1) return first;
  return `${first} (+${kws.length - 1})`;
}

// ──────────────────────────── data loading ────────────────────────────

async function loadTasks() {
  loadingTasks.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: "baidu_keyword" },
    });
    tasks.value = r.data.tasks ?? [];
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

// Parent (MonitorView) calls this after a create/update from the shared
// AddTaskModal so the new task shows up immediately without tab-switching.
defineExpose({ reload: loadTasks });

function backToList(): void {
  selectedId.value = null;
}
</script>

<template>
  <!-- ═══════════════════════════════════════════════════════════
       LEVEL 1: 任务列表（全宽单卡）
  ════════════════════════════════════════════════════════════════ -->
  <template v-if="!selectedId">
    <section
      class="flex min-h-0 flex-1 flex-col"
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
          class="py-10 text-center text-[12.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          暂无百度关键词任务 · 点击「新增任务」开始监测
        </div>

        <!-- Task rows -->
        <template v-else>
          <div
            v-for="(t, i) in tasks"
            :key="t.id"
            class="grid cursor-pointer items-center transition"
            :style="{
              gridTemplateColumns: '1.6fr .7fr .5fr .5fr 1.4fr',
              borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
              borderRadius: '10px',
            }"
            @click="selectedId = t.id"
            @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
            @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
          >
            <!-- 任务名字 + 副标题 -->
            <div class="min-w-0">
              <div
                class="truncate text-[13px] font-medium"
                :style="{ color: 'var(--primary-deep)' }"
              >{{ t.name }}</div>
              <div class="truncate text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                {{ t.last_check_at ? (new Date(t.last_check_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })) : '未跑' }}
                · {{ keywordSummary(t.config) }}
                <template v-if="t.config.target_brand"> · 品牌 {{ t.config.target_brand }}</template>
              </div>
            </div>

            <!-- 命中：仅当此行是选中任务且有 latestMetric 时显示精确值 -->
            <div class="font-display text-[13px] font-bold">
              <template v-if="t.id === selectedId && latestMetric">
                <span>{{ latestMetric.matched_keywords }}/{{ latestMetric.total_keywords }}</span>
                <div class="text-[10.5px] font-normal mt-0.5" :style="{ color: 'var(--ink-3)' }">
                  首条 {{ latestMetric.best_default_first_rank > 0 ? `#${latestMetric.best_default_first_rank}` : '—' }}
                </div>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>

            <!-- 变化：total_default_matches delta（仅选中任务且历史已载） -->
            <div>
              <template v-if="t.id === selectedId && history.length > 0">
                <Pill v-if="history.length === 1" tone="info">首次</Pill>
                <template v-else-if="matchesDelta === null">
                  <span :style="{ color: 'var(--ink-3)' }">—</span>
                </template>
                <template v-else-if="matchesDelta > 0">
                  <Pill tone="ok"><Icon name="arrowUp" :size="10" />+{{ matchesDelta }}</Pill>
                </template>
                <template v-else-if="matchesDelta < 0">
                  <Pill tone="warn"><Icon name="arrowDown" :size="10" />{{ matchesDelta }}</Pill>
                </template>
                <Pill v-else tone="info">持平</Pill>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</span>
            </div>

            <!-- 状态 -->
            <div>
              <Pill v-if="isRunning(t.id)" tone="info">监测中…</Pill>
              <Pill v-else :tone="taskRowState(t).tone">{{ taskRowState(t).statusLabel }}</Pill>
            </div>

            <!-- 操作 -->
            <div class="flex items-center gap-0.5" @click.stop>
              <button
                type="button"
                class="whitespace-nowrap text-[11px]"
                :disabled="isRunning(t.id)"
                :style="{
                  padding: '4px 10px',
                  borderRadius: '999px',
                  color: isRunning(t.id) ? 'var(--ink-3)' : 'var(--primary-deep)',
                  cursor: isRunning(t.id) ? 'not-allowed' : 'pointer',
                  opacity: isRunning(t.id) ? 0.5 : 1,
                }"
                @click="runNowTask(t.id)"
              >{{ isRunning(t.id) ? '监测中…' : '立刻监测' }}</button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--ink-3)' }"
                title="编辑任务"
                @click="openEdit(t)"
              >
                <Icon name="edit" :size="13" />
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--ink-3)' }"
                title="删除任务"
                @click="deleteTask(t)"
              >
                <Icon name="trash" :size="13" />
              </button>
            </div>
          </div>
        </template>
      </div>
    </section>
  </template>

  <!-- ═══════════════════════════════════════════════════════════
       LEVEL 2: 任务详情（← 返回 + 左右双卡）
  ════════════════════════════════════════════════════════════════ -->
  <template v-else>
    <!-- Top header: ← 返回 + task name -->
    <div class="flex flex-shrink-0 items-center gap-3">
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
        @click="backToList"
      >
        <Icon name="arrowLeft" :size="13" />
      </button>
      <div class="min-w-0">
        <div class="font-display truncate text-[14px] font-semibold">
          {{ selectedTask?.name }} · 百度关键词
        </div>
        <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
          {{ (selectedTask?.config.search_keywords ?? []).length }} 个关键词
          <template v-if="selectedTask?.config.target_brand"> · 品牌 {{ selectedTask.config.target_brand }}</template>
          · 检查频率 {{ scheduleLabel(selectedTask?.schedule_cron) }}
        </div>
      </div>
    </div>

    <!-- Two-card layout -->
    <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">

      <!-- ── LEFT CARD: 关键词列表 ──────────────────────────────── -->
      <section
        class="flex min-h-0 flex-col"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <div class="mb-3 flex-shrink-0">
          <div class="font-display text-[14px] font-semibold">关键词列表</div>
          <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            最近一次检查结果
          </div>
        </div>

        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
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

          <!-- Loading -->
          <div
            v-if="loadingHistory"
            class="py-10 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            加载中…
          </div>

          <!-- No data -->
          <div
            v-else-if="!latestMetric"
            class="py-10 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            暂无检查记录
          </div>

          <!-- Keyword rows -->
          <template v-else>
            <div
              v-for="(kw, i) in latestMetric.keywords"
              :key="kw.keyword"
              class="grid items-center"
              :style="{
                gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
                borderBottom: i < latestMetric.keywords.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '12px 8px',
              }"
            >
              <!-- 关键词 -->
              <div class="min-w-0">
                <div class="truncate text-[13px] font-medium">{{ kw.keyword }}</div>
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
                    :style="{ color: kw.news_first_rank > 0 ? 'var(--primary-deep)' : 'var(--ink-3)' }"
                  >
                    {{ kw.news_first_rank > 0 ? `#${kw.news_first_rank}` : '—' }}
                  </div>
                  <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                    命中 {{ kw.news_results.filter(r => r.matches_brand).length }}/{{ kw.news_results.length }}
                  </div>
                </template>
                <span v-else class="text-[11px]" :style="{ color: 'var(--ink-4)' }">无资讯</span>
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

      <!-- ── RIGHT CARD: 任务汇总 ──────────────────────────────── -->
      <section
        class="flex min-h-0 flex-col overflow-y-auto"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <div class="flex-shrink-0">
          <div class="font-display text-[14px] font-semibold">任务汇总</div>
          <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            关键词命中趋势 + 排名详情
          </div>
        </div>

        <!-- KPI 三联 -->
        <div class="mt-3 grid grid-cols-3 gap-3 flex-shrink-0">
          <!-- 本次命中关键词 -->
          <div
            :style="{
              padding: '12px',
              borderRadius: '12px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
            }"
          >
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">本次命中关键词</div>
            <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
              <template v-if="latestMetric">
                {{ latestMetric.matched_keywords }} / {{ latestMetric.total_keywords }}
                <div class="mt-0.5 text-[10.5px] font-normal" :style="{ color: 'var(--ink-3)' }">
                  共 {{ latestMetric.total_default_matches }} 条 / {{ latestMetric.total_keywords }}×10
                </div>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>
          </div>

          <!-- 上次命中关键词 -->
          <div
            :style="{
              padding: '12px',
              borderRadius: '12px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
            }"
          >
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">上次命中关键词</div>
            <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
              <template v-if="prevMetric">
                {{ prevMetric.matched_keywords }} / {{ prevMetric.total_keywords }}
                <div class="mt-0.5 text-[10.5px] font-normal" :style="{ color: 'var(--ink-3)' }">
                  共 {{ prevMetric.total_default_matches }} 条 / {{ prevMetric.total_keywords }}×10
                </div>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>
          </div>

          <!-- 检查频率 -->
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
              {{ scheduleLabel(selectedTask?.schedule_cron) }}
            </div>
          </div>
        </div>

        <!-- Sparkline: matched_keywords 最近 14 次 -->
        <div class="mt-5 flex-shrink-0">
          <div class="mb-2 text-[12px] font-semibold">最近 14 次命中趋势</div>
          <Sparkline
            v-if="sparkPoints.filter(v => v > 0).length > 1"
            :points="sparkPoints"
            :width="380"
            :height="70"
            stroke="var(--primary, #ee6a2a)"
            :axis-labels="sparkLabels"
            fluid
          />
          <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
            无历史数据 —— 跑几次「立刻监测」后会成线。
          </div>
        </div>

        <!-- 排名情况：每关键词折叠段 -->
        <div
          v-if="latestMetric && latestMetric.keywords?.length"
          class="mt-4 flex-shrink-0"
        >
          <div class="mb-2 text-[12px] font-semibold">
            排名情况
            <span class="font-normal ml-1" :style="{ color: 'var(--ink-3)' }">
              ({{ latestMetric.total_keywords }} 个关键词 · 共命中 {{ latestMetric.total_default_matches }} 条)
            </span>
          </div>

          <details
            v-for="(kw, idx) in latestMetric.keywords"
            :key="kw.keyword"
            :open="idx === 0"
            class="mb-2"
            :style="{
              border: '1px solid var(--line)',
              borderRadius: '10px',
              overflow: 'hidden',
            }"
          >
            <!-- Summary / header row -->
            <summary
              :style="{
                cursor: 'pointer',
                padding: '10px 12px',
                background: 'var(--card-2)',
                listStyle: 'none',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                userSelect: 'none',
              }"
            >
              <span class="flex-1 truncate text-[12.5px] font-semibold" :style="{ color: 'var(--ink)' }">
                {{ kw.keyword }}
              </span>
              <span class="flex-shrink-0 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <template v-if="kw.fetch_error">
                  <span :style="{ color: 'var(--red)' }">抓取失败</span>
                </template>
                <template v-else-if="kw.default_matched_count > 0">
                  命中 {{ kw.default_matched_count }}/10 · 首条
                  {{ kw.default_first_rank > 0 ? `#${kw.default_first_rank}` : '—' }}
                </template>
                <template v-else>
                  未命中
                </template>
              </span>
            </summary>

            <!-- Body -->
            <div :style="{ padding: '10px 12px' }">
              <!-- Fetch error badge -->
              <div
                v-if="kw.fetch_error"
                class="mb-2 rounded-lg px-2 py-1 text-[11px]"
                :style="{ background: 'rgba(216,90,72,0.08)', color: 'var(--red)' }"
              >
                抓取失败: {{ kw.fetch_error.slice(0, 120) }}
              </div>

              <template v-else>
                <!-- 默认搜索 sub-section -->
                <div
                  class="mb-3"
                  :style="{
                    borderLeft: '3px solid var(--primary, #ee6a2a)',
                    paddingLeft: '10px',
                  }"
                >
                  <div class="mb-1.5 flex items-center justify-between">
                    <div class="text-[11.5px] font-semibold" :style="{ color: 'var(--ink-2)' }">
                      默认搜索
                      <span class="text-[11px] font-normal ml-1" :style="{ color: 'var(--ink-3)' }">
                        （命中 {{ kw.default_matched_count }} / 10）
                      </span>
                    </div>
                  </div>
                  <template v-if="kw.default_results.length">
                    <div
                      v-for="row in kw.default_results"
                      :key="row.rank"
                      class="mb-1.5 flex items-start gap-3"
                      :style="{
                        padding: '8px 10px',
                        borderRadius: '8px',
                        background: row.matches_brand ? 'var(--primary-soft)' : 'var(--card-2)',
                        border: '1px solid ' + (row.matches_brand ? 'rgba(238,106,42,0.3)' : 'var(--line)'),
                      }"
                    >
                      <span
                        class="font-display text-[13px] font-bold flex-shrink-0"
                        :style="{
                          width: '22px',
                          color: row.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)',
                        }"
                      >#{{ row.rank }}</span>
                      <div class="min-w-0 flex-1">
                        <a
                          :href="row.url"
                          target="_blank"
                          rel="noopener"
                          class="block text-[12.5px] font-medium leading-snug"
                          :style="{
                            color: 'var(--ink)',
                            textDecoration: 'none',
                            display: '-webkit-box',
                            WebkitLineClamp: '2',
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }"
                          :title="row.title"
                        >{{ row.title }}</a>
                        <div class="flex items-center gap-2 mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                          <span class="truncate">{{ row.host }}</span>
                          <span
                            v-if="row.matches_brand"
                            class="flex-shrink-0 ml-auto"
                            :style="{ color: 'var(--primary-deep)', fontWeight: 600 }"
                          >自家 · {{ row.matched_brand }}</span>
                        </div>
                      </div>
                    </div>
                  </template>
                  <div
                    v-else
                    class="py-3 text-center text-[11.5px]"
                    :style="{ color: 'var(--ink-3)' }"
                  >
                    无结果
                  </div>
                </div>

                <!-- 最新资讯 sub-section (only when news_present=true) -->
                <div
                  v-if="kw.news_present"
                  :style="{
                    borderLeft: '3px solid var(--blue, #4f7cff)',
                    paddingLeft: '10px',
                  }"
                >
                  <div class="mb-1.5 flex items-center justify-between">
                    <div class="text-[11.5px] font-semibold" :style="{ color: 'var(--ink-2)' }">
                      最新资讯
                      <span class="text-[11px] font-normal ml-1" :style="{ color: 'var(--ink-3)' }">
                        （{{ kw.news_results.length }} 条）
                      </span>
                    </div>
                    <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                      <span v-if="kw.news_first_rank > 0">
                        首位 <b :style="{ color: 'var(--primary-deep)' }">#{{ kw.news_first_rank }}</b>
                      </span>
                      <span v-else>未命中</span>
                    </div>
                  </div>
                  <div
                    v-for="row in kw.news_results"
                    :key="row.rank"
                    class="mb-1.5 flex items-start gap-3"
                    :style="{
                      padding: '8px 10px',
                      borderRadius: '8px',
                      background: row.matches_brand ? 'rgba(79,124,255,0.08)' : 'var(--card-2)',
                      border: '1px solid ' + (row.matches_brand ? 'rgba(79,124,255,0.3)' : 'var(--line)'),
                    }"
                  >
                    <span
                      class="font-display text-[13px] font-bold flex-shrink-0"
                      :style="{
                        width: '22px',
                        color: row.matches_brand ? 'var(--blue, #4f7cff)' : 'var(--ink-2)',
                      }"
                    >#{{ row.rank }}</span>
                    <div class="min-w-0 flex-1">
                      <a
                        :href="row.url"
                        target="_blank"
                        rel="noopener"
                        class="block text-[12.5px] font-medium leading-snug"
                        :style="{
                          color: 'var(--ink)',
                          textDecoration: 'none',
                          display: '-webkit-box',
                          WebkitLineClamp: '2',
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }"
                        :title="row.title"
                      >{{ row.title }}</a>
                      <div class="flex items-center gap-2 mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                        <span class="truncate">{{ row.host }}</span>
                        <span
                          v-if="row.matches_brand"
                          class="flex-shrink-0 ml-auto"
                          :style="{ color: 'var(--blue, #4f7cff)', fontWeight: 600 }"
                        >自家 · {{ row.matched_brand }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </details>
        </div>

        <!-- 无 metric 占位 -->
        <div
          v-else-if="!loadingHistory && !latestMetric"
          class="mt-6 py-6 text-center text-[12px] flex-shrink-0"
          :style="{ color: 'var(--ink-3)' }"
        >
          暂无检查记录
        </div>

        <!-- 底部：启动监测按钮 -->
        <div
          class="mt-auto pt-5 flex-shrink-0"
          :style="{
            paddingTop: '16px',
            borderTop: '1px solid var(--line)',
          }"
        >
          <button
            type="button"
            class="inline-flex w-full items-center justify-center gap-1.5 px-4 py-2.5 text-[13px] font-medium"
            :disabled="selectedId !== null && isRunning(selectedId)"
            :style="{
              background: selectedId !== null && isRunning(selectedId) ? 'var(--card-2)' : 'var(--primary)',
              color: selectedId !== null && isRunning(selectedId) ? 'var(--ink-3)' : '#fff',
              borderRadius: '999px',
              cursor: selectedId !== null && isRunning(selectedId) ? 'not-allowed' : 'pointer',
              border: '1px solid transparent',
            }"
            @click="runNow"
          >
            <Icon
              :name="selectedId !== null && isRunning(selectedId) ? 'refresh' : 'play'"
              :size="13"
            />
            <span>{{ selectedId !== null && isRunning(selectedId) ? '监测中…' : '▶ 启动监测' }}</span>
          </button>
        </div>
      </section>

    </div>
  </template>
</template>
