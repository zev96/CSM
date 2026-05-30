<script setup lang="ts">
/**
 * 监测中心「AI 卡位」tab —— GEO（生成式引擎卡位）子模块。
 *
 * 自包含组件（IA 大改时会被整体搬走，所以不依赖父组件 props/emit，
 * 自己拉数据、自己管选中态）：
 *   - 任务列表（GET /api/monitor/tasks?type=geo_query）：品牌 / 关键词数 /
 *     平台数 / 最近状态 + 「运行」按钮 + 「看信源榜」。
 *   - 运行（POST /api/monitor/tasks/{id}/run-now）走 useMonitorStatus
 *     乐观标记，跟 MonitorView.runNow / BaiduRankingPage 同套路。
 *   - 实时进度：复用全局 monitorStatus store —— 它已订阅
 *     /api/monitor/events，progress 事件带 progress_current/progress_total
 *     （见 monitor_bus.event_to_dict）。这里只读 progressOf(id) / isRunning(id)。
 *   - 本组件再单独 subscribe("/api/monitor/events", {finished,failed})，
 *     抓完一条就刷新该任务的最近一次 KPI + 任务列表状态（跟
 *     BaiduRankingPage 的「page-specific reactions」同模式）。
 *   - 最近一次 4-KPI 快照：GET /api/monitor/results?task_id=&limit=1 的
 *     metric 块（soc + status_band 色带 / first_rank_rate / sentiment_score /
 *     error_cells>0 时展示失败 cell 数）。
 *   - 信源榜 Top：GET /api/monitor/geo/{id}/citations?days=30 →
 *     domain / source_type / count（CitationRow）。
 *   - 建任务：复用 AddTaskModal（geo_query 分支已在 Task 12 落地）。
 *
 * 视觉沿用 ZhihuMonitorModule 的设计系统 idiom（KPI 卡 card-2 + line 描边、
 * 任务表网格行、Pill 状态徽章），不另造一套观感。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import AddTaskModal from "@/components/monitor/AddTaskModal.vue";
import GeoTaskDetailPage from "@/components/monitor/geo/GeoTaskDetailPage.vue";
import GeoKeywordPlatformDetail from "@/components/monitor/geo/GeoKeywordPlatformDetail.vue";
import type { GeoCellRow } from "@/components/monitor/geo/GeoKeywordPlatformDetail.vue";

import { subscribe } from "@/api/client";
import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import type { Task, CitationRow } from "@/utils/monitor-types";

const sidecar = useSidecar();
const monitorStatus = useMonitorStatus();
const toast = useToast();
const { whenReady } = useSidecarReady();

// ── 状态 ───────────────────────────────────────────────────────────────
const tasks = ref<Task[]>([]);
const loading = ref(false);
const failed = ref(false);

// 当前选中任务（详情卡 + 信源榜跟着它切）。任务列表变化时收敛到第一条
// （跟 ZhihuMonitorModule 的 selectedTaskId fallback watch 同模式）。
const selectedTaskId = ref<number | null>(null);

// L1 ↔ L2 钻入：**仅多关键词任务**点任务名钻入全宽「关键词列表」详情页
// （detailTaskId 非 null 时隐藏 L1 列表 + 右侧概览，显示 GeoTaskDetailPage；
// 返回按钮置 null 还原）。单关键词任务不进 L2，详情内联在 L1 右侧。
// 跟 BaiduRankingPage 的 enterDetail L1→L2 同手势。
const detailTaskId = ref<number | null>(null);
const detailRef = ref<InstanceType<typeof GeoTaskDetailPage> | null>(null);

// 最近一次运行的 metric 块，按 task_id 缓存（GET results?limit=1）。
// metric 字段来自 geo_query adapter（metrics.aggregate + error_cells）：
//   soc / status_band / first_rank_rate / sentiment_score / error_cells …
interface GeoMetric {
  soc?: number;
  status_band?: string;
  first_rank_rate?: number;
  sentiment_score?: number;
  error_cells?: number;
  total?: number;
  mentioned?: number;
}
interface LatestResult {
  checked_at: string;
  status: string;
  rank: number;
  metric: GeoMetric;
}
const latestByTask = ref<Record<number, LatestResult | null>>({});

// 信源榜（当前选中任务，近 30 天）。
const board = ref<CitationRow[]>([]);
const boardLoading = ref(false);

// 单关键词任务的内联多平台详情用的 cells（最近一跑）。只在选中任务恰好 1 个
// 关键词时才拉（多关键词任务走 L2，不需要 L1 内联）。
const inlineCells = ref<GeoCellRow[]>([]);
const inlineCellsLoading = ref(false);

// 建任务 modal
const showAddTask = ref(false);
const editingTask = ref<Task | null>(null);

// ── 派生 ───────────────────────────────────────────────────────────────
const selectedTask = computed<Task | null>(
  () => tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
);
const selectedLatest = computed<LatestResult | null>(() =>
  selectedTaskId.value != null ? latestByTask.value[selectedTaskId.value] ?? null : null,
);

// L2 当前详情任务（点任务名钻入）。任务被删/列表刷新后若已不在，回 L1。
const detailTask = computed<Task | null>(
  () => tasks.value.find((t) => t.id === detailTaskId.value) ?? null,
);

// 演示态：sidecar 不可用或表为空 —— 展示空态引导建任务。
const demoMode = computed(
  () => failed.value || (!loading.value && tasks.value.length === 0),
);

function keywordCount(t: Task): number {
  const kws = t.config?.keywords;
  return Array.isArray(kws) ? kws.length : 0;
}
function platformCount(t: Task): number {
  const ps = t.config?.platforms;
  return Array.isArray(ps) ? ps.length : 0;
}

// 单关键词任务 = 不进 L2，详情内联在 L1 右侧（没有可挑选/列表的关键词）。
// 多关键词任务 = 任务名是钻入 L2 的彩色热区。
function isSingleKeyword(t: Task): boolean {
  return keywordCount(t) === 1;
}
// 选中任务（恰好 1 关键词时）的那个关键词名。
const singleKeywordName = computed<string | null>(() => {
  const t = selectedTask.value;
  if (!t || !isSingleKeyword(t)) return null;
  const kws = t.config?.keywords;
  return Array.isArray(kws) && kws.length ? String(kws[0]) : null;
});
// 内联详情喂给 GeoKeywordPlatformDetail 的 cells —— 过滤到该关键词
// （cells 已是该任务最近一跑的全部平台 cell）。
const inlineKeywordCells = computed<GeoCellRow[]>(() => {
  const kw = singleKeywordName.value;
  if (!kw) return [];
  return inlineCells.value.filter((c) => c.keyword === kw);
});

// 百分比展示（soc / first_rank_rate 是 0–1 ratio）。
function pct(v: number | undefined | null): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}
// 情感得分 -1..1 → 一位小数；na/空显示 —。
function sentimentText(v: number | undefined | null): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}

// 曝光度色带 —— 跟 metrics.band 一致：strong 绿 / weak 橙 / hidden 红/灰。
function bandColor(band: string | undefined): string {
  if (band === "strong") return "var(--green)";
  if (band === "weak") return "var(--primary-deep, #c9521f)";
  return "var(--red, #d85a48)"; // hidden / 未知
}
function bandLabel(band: string | undefined): string {
  if (band === "strong") return "强曝光";
  if (band === "weak") return "弱曝光";
  if (band === "hidden") return "未露出";
  return "—";
}

// 「部分失败」判定 —— 运行级 status 仍是 "ok"（没全军覆没），但 metric
// 里有 error_cells>0（部分平台够不到 / 被拦）。这种半成功要跟「正常」
// （全 ok）和「失败」（运行级 failed）区分开，让用户知道这次数据不全。
function isPartialFail(t: Task): boolean {
  const r = latestByTask.value[t.id];
  if (!r || r.status !== "ok") return false;
  return (r.metric?.error_cells ?? 0) > 0;
}

// 任务最近状态 Pill —— 优先用最近一次 result.status，回退 task.last_status。
function statusTone(t: Task): "ok" | "warn" | "alert" | "info" {
  if (isPartialFail(t)) return "warn"; // 部分失败 = 琥珀
  const s = latestByTask.value[t.id]?.status ?? t.last_status;
  if (s === "ok") return "ok";
  if (s === "failed") return "alert";
  if (s === "risk_control") return "warn";
  return "info";
}
function statusText(t: Task): string {
  if (isPartialFail(t)) return "部分失败";
  const s = latestByTask.value[t.id]?.status ?? t.last_status;
  if (s === "ok") return "正常";
  if (s === "failed") return "失败";
  if (s === "risk_control") return "风控";
  if (!s) return "未运行";
  return s;
}

// 进度（运行中才有）。store 已全局订阅 SSE progress 事件。
function progressRatio(taskId: number): number | null {
  const p = monitorStatus.progressOf(taskId);
  if (!p || p.total <= 0) return null;
  return p.current / p.total;
}
function isRunning(taskId: number): boolean {
  return monitorStatus.isRunning(taskId);
}

// ── 数据加载 ───────────────────────────────────────────────────────────
async function loadTasks(): Promise<void> {
  loading.value = true;
  failed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: "geo_query" },
    });
    tasks.value = r.data?.tasks ?? [];
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

// 拉每条任务最近一次 result（只 limit=1，要 metric KPI 块）。
async function loadLatest(taskId: number): Promise<void> {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 1 },
    });
    const rows: any[] = r.data?.results ?? [];
    latestByTask.value = { ...latestByTask.value, [taskId]: rows[0] ?? null };
  } catch {
    // 静默：拿不到 latest 的 task 在 UI 上显示 "—"，不弹 toast 刷屏。
  }
}

async function loadAllLatest(): Promise<void> {
  if (!tasks.value.length) return;
  await Promise.all(tasks.value.map((t) => loadLatest(t.id)));
}

async function loadBoard(taskId: number): Promise<void> {
  boardLoading.value = true;
  try {
    const r = await sidecar.client.get(`/api/monitor/geo/${taskId}/citations`, {
      params: { days: 30 },
    });
    board.value = r.data?.leaderboard ?? [];
  } catch {
    board.value = [];
  } finally {
    boardLoading.value = false;
  }
}

// 拉选中任务最近一跑的全部 cell —— 单关键词任务在 L1 右侧内联多平台详情用。
// 多关键词任务不调（详情在 L2 自取），避免无谓请求。
async function loadInlineCells(taskId: number): Promise<void> {
  const t = tasks.value.find((x) => x.id === taskId);
  if (!t || !isSingleKeyword(t)) {
    inlineCells.value = [];
    return;
  }
  inlineCellsLoading.value = true;
  try {
    const r = await sidecar.client.get(`/api/monitor/geo/${taskId}/latest-cells`);
    inlineCells.value = (r.data?.cells ?? []) as GeoCellRow[];
  } catch {
    inlineCells.value = [];
  } finally {
    inlineCellsLoading.value = false;
  }
}

// ── 操作 ───────────────────────────────────────────────────────────────
function selectTask(taskId: number): void {
  selectedTaskId.value = taskId;
  void loadBoard(taskId);
  void loadInlineCells(taskId); // 单关键词任务用；多关键词内部会清空
}

// 钻入 / 退出 L2 卡位仪表盘 —— 仅多关键词任务（任务名点击进，返回按钮出）。
// 单关键词任务不进 L2，点名字等同选中（详情已内联在右侧）。
function openDetail(taskId: number): void {
  const t = tasks.value.find((x) => x.id === taskId);
  if (t && isSingleKeyword(t)) {
    selectTask(taskId);
    return;
  }
  detailTaskId.value = taskId;
  selectedTaskId.value = taskId; // 同步选中态，返回时右侧概览停在同一条
}
function closeDetail(): void {
  detailTaskId.value = null;
}

async function runNow(taskId: number): Promise<void> {
  // 乐观标记 —— SSE started 可能要等 worker 拿到 slot 才发，先点亮进度。
  monitorStatus.markRunning(taskId);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${taskId}/run-now`);
    toast.info("已派发，正在监测…");
  } catch (e: any) {
    monitorStatus.clearRunning(taskId);
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`派发失败：${detail}`);
  }
}

async function cancelTask(taskId: number): Promise<void> {
  try {
    const delivered = await monitorStatus.cancel(taskId);
    if (delivered) {
      toast.info("已发送停止信号，正在等当前 cell 跑完退出（约 5-30s/cell）");
    } else {
      toast.warn("没有可停止的任务（可能已经结束）");
    }
  } catch (e: any) {
    toast.error(`停止失败：${e?.message ?? e}`);
  }
}

function openAddTask(): void {
  editingTask.value = null;
  showAddTask.value = true;
}
function openEditTask(t: Task): void {
  editingTask.value = t;
  showAddTask.value = true;
}
function onAddTaskClose(v: boolean): void {
  showAddTask.value = v;
  if (!v) editingTask.value = null;
}

async function deleteTask(taskId: number): Promise<void> {
  if (
    !(await confirmDialog("确定删除这个 AI 卡位任务？历史结果会一并删除。", {
      title: "删除监测任务",
    }))
  )
    return;
  try {
    await sidecar.client.delete(`/api/monitor/tasks/${taskId}`);
    toast.success("任务已删除");
    if (detailTaskId.value === taskId) detailTaskId.value = null; // 删的是正看着的 → 退回 L1
    if (selectedTaskId.value === taskId) {
      selectedTaskId.value = null;
      board.value = [];
    }
    await onTaskMutated();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

// 建/改任务后刷新列表 + 最近结果。
async function onTaskMutated(): Promise<void> {
  await loadTasks();
  await loadAllLatest();
}

// ── 任务列表变化 → 收敛选中态（默认第一条），并触发该任务信源榜 ───────
watch(
  tasks,
  (list) => {
    if (list.length === 0) {
      selectedTaskId.value = null;
      board.value = [];
      inlineCells.value = [];
      return;
    }
    if (
      selectedTaskId.value == null ||
      !list.find((t) => t.id === selectedTaskId.value)
    ) {
      selectedTaskId.value = list[0].id;
      void loadBoard(list[0].id);
      void loadInlineCells(list[0].id);
    }
  },
  { immediate: false },
);

// ── 生命周期 + SSE（page-specific reactions）───────────────────────────
let stopSse: (() => void) | null = null;

onMounted(async () => {
  try {
    await whenReady();
    await loadTasks();
    await loadAllLatest();
    // store 负责全局 running/progress（含 SSE progress 事件）；这里只挂
    // page-specific 反应：抓完/失败时刷新对应任务的 latest + 状态。
    void monitorStatus.hydrate();
    stopSse = subscribe("/api/monitor/events", {
      finished: (d: any) => {
        if (typeof d.task_id !== "number") return;
        const t = tasks.value.find((x) => x.id === d.task_id);
        if (t) {
          t.last_check_at = d.at;
          t.last_status = d.result?.status ?? t.last_status;
        }
        void loadLatest(d.task_id);
        // 当前正看着这条 → 顺带刷信源榜 + 内联 cells（这次跑可能带来新数据）。
        if (selectedTaskId.value === d.task_id) {
          void loadBoard(d.task_id);
          void loadInlineCells(d.task_id);
        }
        // L2 详情页开着同一条 → 让它全量刷新（KPI + 关键词列表 + 信源）。
        if (detailTaskId.value === d.task_id) void detailRef.value?.refresh();
      },
      failed: (d: any) => {
        if (typeof d.task_id !== "number") return;
        const t = tasks.value.find((x) => x.id === d.task_id);
        if (t) t.last_status = "failed";
        void loadLatest(d.task_id);
        if (detailTaskId.value === d.task_id) void detailRef.value?.refresh();
      },
    });
  } catch {
    failed.value = true;
  }
});

onUnmounted(() => {
  if (stopSse) stopSse();
});
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col" :style="{ gap: '24px' }">
    <!-- ════════ L2：全宽关键词列表（仅多关键词任务，点任务名钻入；返回还原 L1）════════ -->
    <GeoTaskDetailPage
      v-if="detailTask"
      ref="detailRef"
      :task="detailTask"
      @back="closeDetail"
      @run="runNow"
      @cancel="cancelTask"
      @edit="openEditTask"
      @delete="deleteTask"
    />

    <!-- ════════ L1：任务列表 + 右侧概览 ════════ -->
    <!-- table + detail -->
    <div v-else class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
      <!-- ════════ 左：任务列表 ════════ -->
      <section
        class="flex h-full min-h-0 flex-col overflow-hidden"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
          <div class="min-w-0">
            <div class="font-display text-[14px] font-semibold">卡位任务</div>
          </div>
          <button
            type="button"
            class="inline-flex flex-shrink-0 items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
            :style="{
              background: 'var(--primary)',
              color: '#fff',
              borderRadius: '999px',
            }"
            @click="openAddTask"
          >
            <Icon name="plus" :size="12" />
            <span>新建任务</span>
          </button>
        </div>

        <!-- 列头：品牌 / 关键词 / 平台 / 状态 / 操作 -->
        <div
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.5fr .7fr .7fr .8fr 1fr',
            letterSpacing: '1.2px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>品牌 / 任务</div>
          <div class="text-center">关键词</div>
          <div class="text-center">平台</div>
          <div class="text-center">状态</div>
          <div class="text-center">操作</div>
        </div>

        <!-- 滚动数据区 -->
        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <!-- 空态（无 sidecar / 无任务）-->
          <div
            v-if="demoMode"
            class="py-10 text-center text-[12.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            暂无卡位任务 · 点击「新建任务」开始监测 AI 平台卡位
          </div>

          <!-- 任务行 -->
          <div
            v-for="(t, i) in tasks"
            :key="t.id"
            class="grid cursor-pointer items-center transition"
            :style="{
              gridTemplateColumns: '1.5fr .7fr .7fr .8fr 1fr',
              background: selectedTaskId === t.id ? 'var(--card-2)' : 'transparent',
              borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
              borderRadius: '10px',
            }"
            @click="selectTask(t.id)"
          >
            <div class="min-w-0">
              <!--
                多关键词任务：任务名是「点击进 L2 关键词列表」的彩色热区
                （primary-deep，跟 ZhihuMonitorModule 的批次名链接同款）；
                整行点击只把右侧概览定位到这条（selectTask）。@click.stop 防止
                点名字又触发行 select。
                单关键词任务：没有可挑选的关键词列表，不进 L2 —— 任务名渲染成
                普通文字（点击只选中，详情已内联在右侧）。
              -->
              <button
                v-if="!isSingleKeyword(t)"
                type="button"
                class="block w-full truncate text-left text-[13px] font-medium"
                :style="{ color: 'var(--primary-deep)', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }"
                title="打开关键词列表（关键词 × 平台 + 多平台详情）"
                @click.stop="openDetail(t.id)"
              >{{ t.name }}</button>
              <div
                v-else
                class="truncate text-[13px] font-medium"
                :style="{ color: 'var(--ink)' }"
                :title="t.name"
              >{{ t.name }}</div>
              <!-- 运行中进度条（store 维护 SSE progress 状态）-->
              <div v-if="isRunning(t.id)" class="mt-1.5 flex items-center gap-2">
                <ProgressBar :value="progressRatio(t.id)" :height="5" />
                <span
                  v-if="monitorStatus.progressOf(t.id)"
                  class="flex-shrink-0 text-[10.5px]"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  {{ monitorStatus.progressOf(t.id)!.current }} /
                  {{ monitorStatus.progressOf(t.id)!.total }}
                </span>
                <span
                  v-else
                  class="flex-shrink-0 text-[10.5px]"
                  :style="{ color: 'var(--ink-3)' }"
                >排队中…</span>
              </div>
            </div>
            <div
              class="text-center font-display text-[13px] font-bold"
            >{{ keywordCount(t) }}</div>
            <div
              class="text-center font-display text-[13px] font-bold"
            >{{ platformCount(t) }}</div>
            <div class="flex items-center justify-center">
              <Pill :tone="statusTone(t)">{{ statusText(t) }}</Pill>
            </div>
            <div class="flex items-center justify-center gap-1">
              <button
                v-if="isRunning(t.id)"
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--red, #d85a48)', cursor: 'pointer' }"
                title="停止监测"
                @click.stop="cancelTask(t.id)"
              >
                <Icon name="x" :size="13" />
              </button>
              <button
                v-else
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--primary-deep)', cursor: 'pointer' }"
                title="立刻运行"
                @click.stop="runNow(t.id)"
              >
                <Icon name="play" :size="13" />
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--ink-3)', cursor: 'pointer' }"
                title="编辑任务"
                @click.stop="openEditTask(t)"
              >
                <Icon name="edit" :size="13" />
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--ink-3)', cursor: 'pointer' }"
                title="删除任务"
                @click.stop="deleteTask(t.id)"
              >
                <Icon name="trash" :size="13" />
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- ════════ 右：详情（4-KPI 快照 + 信源榜）════════ -->
      <section
        class="flex h-full min-h-0 flex-col overflow-hidden"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <!-- 无选中（空表）-->
        <div
          v-if="!selectedTask"
          class="py-6 text-[12.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          点击左侧任意任务查看卡位概览与信源榜。
        </div>

        <template v-else>
          <!-- 头：任务名 + 运行按钮 -->
          <div class="flex flex-shrink-0 items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="font-display text-[14px] font-semibold">
                「{{ selectedTask.name }}」
              </div>
              <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                {{ keywordCount(selectedTask) }} 个关键词 ·
                {{ platformCount(selectedTask) }} 个 AI 平台
              </div>
            </div>
            <button
              v-if="!isRunning(selectedTask.id)"
              type="button"
              class="inline-flex flex-shrink-0 items-center gap-1 px-3 py-1.5 text-[11.5px] font-medium"
              :style="{
                background: 'var(--primary)',
                color: '#fff',
                borderRadius: '999px',
              }"
              title="立刻运行一次"
              @click="runNow(selectedTask.id)"
            >
              <Icon name="play" :size="12" />
              <span>运行</span>
            </button>
            <button
              v-else
              type="button"
              class="inline-flex flex-shrink-0 items-center gap-1 px-3 py-1.5 text-[11.5px] font-medium"
              :style="{
                background: 'var(--card-2)',
                color: 'var(--red, #d85a48)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
              }"
              title="停止监测"
              @click="cancelTask(selectedTask.id)"
            >
              <Icon name="x" :size="12" />
              <span>停止</span>
            </button>
          </div>

          <!-- 运行中进度（详情区也放一条，醒目）-->
          <div v-if="isRunning(selectedTask.id)" class="mt-3 flex-shrink-0">
            <div class="mb-1.5 flex items-center justify-between text-[11px]" :style="{ color: 'var(--ink-3)' }">
              <span>正在采集各平台回答…</span>
              <span v-if="monitorStatus.progressOf(selectedTask.id)">
                {{ monitorStatus.progressOf(selectedTask.id)!.current }} /
                {{ monitorStatus.progressOf(selectedTask.id)!.total }}
              </span>
            </div>
            <ProgressBar :value="progressRatio(selectedTask.id)" :height="6" />
          </div>

          <!-- 4-KPI 快照（最近一次 result.metric）-->
          <div class="mt-3 grid flex-shrink-0 grid-cols-2 gap-3">
            <!-- 曝光度 SoC + 色带 -->
            <div
              :style="{
                padding: '12px',
                borderRadius: '12px',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">曝光度 SoC</div>
              <div class="mt-1 flex items-baseline gap-2">
                <span
                  class="font-display font-bold"
                  :style="{ fontSize: '20px', color: bandColor(selectedLatest?.metric?.status_band) }"
                >{{ selectedLatest ? pct(selectedLatest.metric?.soc) : "—" }}</span>
                <span
                  v-if="selectedLatest?.metric?.status_band"
                  class="text-[11px]"
                  :style="{ color: bandColor(selectedLatest.metric.status_band) }"
                >{{ bandLabel(selectedLatest.metric.status_band) }}</span>
              </div>
            </div>
            <!-- 首推率 -->
            <div
              :style="{
                padding: '12px',
                borderRadius: '12px',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">首推率</div>
              <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                {{ selectedLatest ? pct(selectedLatest.metric?.first_rank_rate) : "—" }}
              </div>
            </div>
            <!-- 情感得分 -->
            <div
              :style="{
                padding: '12px',
                borderRadius: '12px',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">情感得分</div>
              <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                {{ selectedLatest ? sentimentText(selectedLatest.metric?.sentiment_score) : "—" }}
              </div>
            </div>
            <!-- 采集失败 cell（>0 才高亮，让失败的运行可见）-->
            <div
              :style="{
                padding: '12px',
                borderRadius: '12px',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">采集失败</div>
              <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                <template v-if="selectedLatest">
                  <span
                    v-if="(selectedLatest.metric?.error_cells ?? 0) > 0"
                    :style="{ color: 'var(--red, #d85a48)' }"
                  >{{ selectedLatest.metric!.error_cells }} 个</span>
                  <span v-else :style="{ color: 'var(--green)', fontSize: '16px' }">全部成功</span>
                </template>
                <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
              </div>
            </div>
          </div>

          <!-- 还没跑过的提示 -->
          <div
            v-if="!selectedLatest"
            class="mt-3 flex-shrink-0 text-[11.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            该任务还没有运行记录 · 点「运行」采集一次后显示卡位数据。
          </div>

          <!--
            ════ 单关键词任务：多平台详情内联（不进 L2）════
            该任务恰好 1 个关键词 → 没有可挑选的关键词列表，详情直接内联在
            KPI 下方（复用 GeoKeywordPlatformDetail，与 L2 右侧点关键词同款块）。
            多关键词任务走 L2 关键词列表，这里不渲染。自带 maxHeight + 滚动，
            避免详情过长把下方信源榜挤没。
          -->
          <div
            v-if="singleKeywordName"
            class="mt-4 flex-shrink-0"
          >
            <div class="mb-2 flex items-center justify-between gap-2">
              <div class="text-[12px] font-semibold">
                多平台详情
                <span class="ml-1 text-[11px] font-normal" :style="{ color: 'var(--ink-3)' }">
                  · {{ singleKeywordName }}
                </span>
              </div>
              <button
                type="button"
                class="inline-flex items-center gap-1 text-[11px]"
                :style="{ color: 'var(--ink-3)', background: 'transparent', cursor: 'pointer' }"
                title="刷新多平台详情"
                @click="loadInlineCells(selectedTask.id)"
              >
                <Icon name="refresh" :size="11" />
                <span>刷新</span>
              </button>
            </div>
            <div
              v-if="inlineCellsLoading"
              class="py-6 text-center text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >加载中…</div>
            <div v-else :style="{ maxHeight: '420px', overflowY: 'auto' }">
              <GeoKeywordPlatformDetail :keyword="singleKeywordName" :cells="inlineKeywordCells" />
            </div>
          </div>

          <!-- ════ 信源榜 Top（近 30 天）════ -->
          <div class="mt-5 flex min-h-0 flex-1 flex-col">
            <div class="mb-2 flex flex-shrink-0 items-center justify-between">
              <div class="text-[12px] font-semibold">信源榜 · 近 30 天</div>
              <button
                type="button"
                class="inline-flex items-center gap-1 text-[11px]"
                :style="{ color: 'var(--ink-3)', background: 'transparent', cursor: 'pointer' }"
                title="刷新信源榜"
                @click="loadBoard(selectedTask.id)"
              >
                <Icon name="refresh" :size="11" />
                <span>刷新</span>
              </button>
            </div>

            <div class="min-h-0 flex-1 overflow-y-auto">
              <div
                v-if="boardLoading"
                class="py-6 text-center text-[12px]"
                :style="{ color: 'var(--ink-3)' }"
              >加载中…</div>
              <div
                v-else-if="board.length === 0"
                class="py-6 text-center text-[12px]"
                :style="{ color: 'var(--ink-3)' }"
              >暂无信源数据 · 运行后 AI 引用的来源域名会汇总到这里。</div>

              <table v-else class="w-full" :style="{ borderCollapse: 'collapse' }">
                <thead>
                  <tr
                    class="text-[10.5px] uppercase"
                    :style="{ letterSpacing: '1px', color: 'var(--ink-3)' }"
                  >
                    <th class="py-1.5 text-left" :style="{ fontWeight: 500 }">域名</th>
                    <th class="py-1.5 text-left" :style="{ fontWeight: 500 }">类型</th>
                    <th class="py-1.5 text-right" :style="{ fontWeight: 500 }">引用</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in board"
                    :key="row.domain"
                    :style="{ borderTop: '1px solid var(--line)' }"
                  >
                    <td class="truncate py-2 text-[12.5px] font-medium" :style="{ maxWidth: '0' }">
                      {{ row.domain || "—" }}
                    </td>
                    <td class="py-2">
                      <Pill tone="info">{{ row.source_type }}</Pill>
                    </td>
                    <td class="py-2 text-right font-display text-[13px] font-bold">
                      {{ row.count }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </section>
    </div>

    <!-- 建/改任务 modal（复用 AddTaskModal 的 geo_query 分支）-->
    <AddTaskModal
      :open="showAddTask"
      :editing-task="editingTask as any"
      default-type="geo_query"
      @update:open="onAddTaskClose"
      @created="onTaskMutated"
      @updated="onTaskMutated"
    />
  </div>
</template>
