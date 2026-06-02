<script setup lang="ts">
/**
 * 监测中心「AI 卡位」tab —— GEO（生成式引擎卡位）子模块。
 *
 * 整页 master-detail（按 design_handoff_geo_fullpage 重建）：
 *   - 左栏（340px）：卡位任务列表 = 总任务(品牌) → 子任务(关键词) 两级可展开 +
 *     「搜索品牌/关键词」框 + 「＋新建任务」。一个 geo_query 任务 = 一个品牌，
 *     config.keywords[] = 关键词。展开品牌行 → 显其关键词子行；点关键词 → 右栏
 *     渲染该关键词的三页签详情。品牌行：名 + 「N 关键词」+ 状态药丸(正常/排队中/
 *     部分失败)；关键词子行：仅关键词文字，选中=橙竖条+橙底。
 *   - 右栏：选中关键词的三页签详情（GeoKeywordDetail：概览/平台对比/竞争·信源），
 *     数据由 useGeoKeywordDetail 从既有只读端点装配（不改后端）。
 *   - 顶部模块切换 tab（知乎问题/平台评论/百度排名/AI 卡位）已是 MonitorView 的
 *     pivot —— 本组件不重建，只渲染左右两栏主体。
 *
 * 自包含（IA 大改会整体搬走，不依赖父 props/emit）：自己拉 geo_query 任务、
 * 跑（run-now 走 useMonitorStatus 乐观标记）、订阅 SSE finished/failed 刷新选中
 * 关键词详情 + 任务列表状态。建任务复用 AddTaskModal 的 geo_query 分支。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import AddTaskModal from "@/components/monitor/AddTaskModal.vue";
import GeoKeywordDetail from "@/components/monitor/geo/GeoKeywordDetail.vue";
import { useGeoKeywordDetail } from "@/components/monitor/geo/geoDetail";

import { subscribe } from "@/api/client";
import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import type { Task } from "@/utils/monitor-types";

const sidecar = useSidecar();
const monitorStatus = useMonitorStatus();
const toast = useToast();
const { whenReady } = useSidecarReady();

// ── 状态 ───────────────────────────────────────────────────────────────
const tasks = ref<Task[]>([]);
const loading = ref(false);
const failed = ref(false);

// 左栏展开的品牌(任务) id（单选可折叠）+ 选中的关键词。
const expandedTaskId = ref<number | null>(null);
const selectedTaskId = ref<number | null>(null);
const selectedKeyword = ref<string | null>(null);

// 搜索框（搜品牌/关键词）。
const search = ref("");

// 每条任务最近一次 result（拿 metric.error_cells 判「部分失败」+ status）。
interface GeoMetric {
  error_cells?: number;
}
interface LatestResult {
  checked_at: string;
  status: string;
  rank: number;
  metric: GeoMetric;
}
const latestByTask = ref<Record<number, LatestResult | null>>({});

// 建/改任务 modal
const showAddTask = ref(false);
const editingTask = ref<Task | null>(null);

// ── 派生：任务 → 品牌/关键词 ─────────────────────────────────────────────
function keywordsOf(t: Task): string[] {
  const kws = t.config?.keywords;
  return Array.isArray(kws) ? kws.filter(Boolean).map(String) : [];
}
function brandOf(t: Task): string {
  return String(t.config?.brand ?? t.name ?? "");
}
function brandTermsOf(t: Task | null): string[] {
  if (!t) return [];
  const brand = brandOf(t);
  const aliases = Array.isArray(t.config?.brand_aliases)
    ? t.config!.brand_aliases.filter(Boolean).map(String)
    : [];
  return [brand, ...aliases].filter(Boolean);
}
function platformCountOf(t: Task): number {
  const ps = t.config?.platforms;
  return Array.isArray(ps) ? ps.length : 0;
}

const selectedTask = computed<Task | null>(
  () => tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
);
const selectedBrandTerms = computed<string[]>(() => brandTermsOf(selectedTask.value));
const selectedPlatformCount = computed<number>(() =>
  selectedTask.value ? platformCountOf(selectedTask.value) : 0,
);

// 搜索过滤：品牌名命中 → 整个品牌(含全部关键词)；否则只留命中关键词的品牌。
interface BrandNode {
  task: Task;
  brand: string;
  keywords: string[];
}
const filteredTree = computed<BrandNode[]>(() => {
  const q = search.value.trim().toLowerCase();
  const out: BrandNode[] = [];
  for (const t of tasks.value) {
    const brand = brandOf(t);
    const kws = keywordsOf(t);
    if (!q) {
      out.push({ task: t, brand, keywords: kws });
      continue;
    }
    const brandHit = brand.toLowerCase().includes(q);
    if (brandHit) {
      out.push({ task: t, brand, keywords: kws });
    } else {
      const matched = kws.filter((k) => k.toLowerCase().includes(q));
      if (matched.length) out.push({ task: t, brand, keywords: matched });
    }
  }
  return out;
});

// 演示态：sidecar 不可用或表为空。
const demoMode = computed(() => failed.value || (!loading.value && tasks.value.length === 0));

// ── 任务状态药丸（品牌行右侧）──────────────────────────────────────────
function isPartialFail(t: Task): boolean {
  const r = latestByTask.value[t.id];
  if (!r || r.status !== "ok") return false;
  return (r.metric?.error_cells ?? 0) > 0;
}
function statusTone(t: Task): "ok" | "warn" | "alert" | "info" {
  if (monitorStatus.isRunning(t.id)) return "warn"; // 排队中/运行中
  if (isPartialFail(t)) return "warn";
  const s = latestByTask.value[t.id]?.status ?? t.last_status;
  if (s === "ok") return "ok";
  if (s === "failed") return "alert";
  if (s === "risk_control") return "warn";
  return "info";
}
function statusText(t: Task): string {
  if (monitorStatus.isRunning(t.id)) return "排队中";
  if (isPartialFail(t)) return "部分失败";
  const s = latestByTask.value[t.id]?.status ?? t.last_status;
  if (s === "ok") return "正常";
  if (s === "failed") return "失败";
  if (s === "risk_control") return "风控";
  if (!s) return "未运行";
  return s;
}

// 进度（运行中才有）。
function progressRatio(taskId: number): number | null {
  const p = monitorStatus.progressOf(taskId);
  if (!p || p.total <= 0) return null;
  return p.current / p.total;
}
function isRunning(taskId: number): boolean {
  return monitorStatus.isRunning(taskId);
}

// ── 右栏详情：装配选中关键词数据（不改后端，前端派生）──────────────────
const { detail, loading: detailLoading, reload: reloadDetail } = useGeoKeywordDetail(
  selectedTaskId,
  selectedKeyword,
  selectedBrandTerms,
);

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

async function loadLatest(taskId: number): Promise<void> {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 1 },
    });
    const rows: any[] = r.data?.results ?? [];
    latestByTask.value = { ...latestByTask.value, [taskId]: rows[0] ?? null };
  } catch {
    // 静默：拿不到 latest 的 task 在 UI 上显示「未运行」，不弹 toast。
  }
}
async function loadAllLatest(): Promise<void> {
  if (!tasks.value.length) return;
  await Promise.all(tasks.value.map((t) => loadLatest(t.id)));
}

// ── 选择 / 展开 ─────────────────────────────────────────────────────────
function toggleBrand(taskId: number): void {
  expandedTaskId.value = expandedTaskId.value === taskId ? null : taskId;
}
function selectKeyword(taskId: number, keyword: string): void {
  selectedTaskId.value = taskId;
  selectedKeyword.value = keyword;
  // 确保该品牌展开（点关键词时品牌一定是展开的，这里兜底）。
  expandedTaskId.value = taskId;
}

// 默认选中：第一个品牌 → 展开 → 选其首个关键词。
function selectFirstKeyword(): void {
  const first = tasks.value[0];
  if (!first) {
    selectedTaskId.value = null;
    selectedKeyword.value = null;
    expandedTaskId.value = null;
    return;
  }
  const kws = keywordsOf(first);
  expandedTaskId.value = first.id;
  selectedTaskId.value = first.id;
  selectedKeyword.value = kws.length ? kws[0] : null;
}

// ── 操作 ───────────────────────────────────────────────────────────────
async function runNow(taskId: number): Promise<void> {
  monitorStatus.markRunning(taskId);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${taskId}/run-now`);
    toast.info("已派发，正在监测…");
  } catch (e: any) {
    monitorStatus.clearRunning(taskId);
    const detailMsg = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`派发失败：${detailMsg}`);
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
    if (selectedTaskId.value === taskId) {
      selectedTaskId.value = null;
      selectedKeyword.value = null;
    }
    if (expandedTaskId.value === taskId) expandedTaskId.value = null;
    await onTaskMutated();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

async function onTaskMutated(): Promise<void> {
  await loadTasks();
  await loadAllLatest();
}

// ── 任务列表变化 → 收敛选中态（默认第一个品牌的首个关键词）───────────────
watch(
  tasks,
  (list) => {
    if (list.length === 0) {
      selectFirstKeyword();
      return;
    }
    // 选中任务仍在？校验关键词也仍在；否则收敛到第一个品牌首词。
    const cur = list.find((t) => t.id === selectedTaskId.value);
    if (!cur) {
      selectFirstKeyword();
      return;
    }
    const kws = keywordsOf(cur);
    if (selectedKeyword.value == null || !kws.includes(selectedKeyword.value)) {
      selectedKeyword.value = kws.length ? kws[0] : null;
    }
    if (expandedTaskId.value == null) expandedTaskId.value = cur.id;
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
    selectFirstKeyword();
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
        // 当前正看着这条任务的某关键词 → 热刷新右栏详情。
        if (selectedTaskId.value === d.task_id) void reloadDetail();
      },
      failed: (d: any) => {
        if (typeof d.task_id !== "number") return;
        const t = tasks.value.find((x) => x.id === d.task_id);
        if (t) t.last_status = "failed";
        void loadLatest(d.task_id);
        if (selectedTaskId.value === d.task_id) void reloadDetail();
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
  <!-- 两栏主体：左任务列表(340px) + 右关键词详情。高度填满父容器。 -->
  <div
    class="grid min-h-0 flex-1"
    :style="{ gridTemplateColumns: '340px 1fr', gap: '18px' }"
  >
    <!-- ════════ 左：卡位任务列表（品牌 → 关键词）════════ -->
    <section
      class="flex h-full min-h-0 flex-col overflow-hidden"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)' }"
    >
      <!-- 头（不滚动）-->
      <div
        class="flex flex-shrink-0 items-center justify-between"
        :style="{ gap: '12px', padding: '18px 20px 14px' }"
      >
        <div class="font-display" :style="{ fontSize: '16px', fontWeight: 700 }">卡位任务</div>
        <button
          type="button"
          class="inline-flex flex-shrink-0 items-center"
          :style="{ gap: '5px', padding: '7px 13px', fontSize: '12px', fontWeight: 600, color: '#fff', background: 'var(--primary)', border: 'none', borderRadius: '999px', cursor: 'pointer', fontFamily: 'inherit' }"
          @click="openAddTask"
        >
          <Icon name="plus" :size="12" />
          <span>新建任务</span>
        </button>
      </div>

      <!-- 搜索框（不滚动）-->
      <div :style="{ padding: '0 16px 12px', flexShrink: 0 }">
        <div
          class="flex items-center"
          :style="{ gap: '8px', padding: '9px 12px', borderRadius: '10px', background: 'var(--card-2)', border: '1px solid var(--line)' }"
        >
          <Icon name="search" :size="13" :stroke="1.8" :style="{ color: 'var(--ink-4)', flexShrink: 0 }" />
          <input
            v-model="search"
            type="text"
            placeholder="搜索品牌 / 关键词"
            :style="{ flex: 1, minWidth: 0, fontSize: '12px', color: 'var(--ink-2)', background: 'transparent', border: 'none', outline: 'none', fontFamily: 'inherit' }"
          />
        </div>
      </div>

      <!-- 列表区（可滚动，品牌 → 关键词两级）-->
      <div class="geo-scroll min-h-0 flex-1 overflow-y-auto" :style="{ padding: '0 12px 12px' }">
        <!-- 空态 -->
        <div
          v-if="demoMode"
          class="text-center"
          :style="{ padding: '40px 8px', fontSize: '12.5px', color: 'var(--ink-3)' }"
        >暂无卡位任务 · 点击「新建任务」开始监测 AI 平台卡位</div>

        <!-- 搜索无命中 -->
        <div
          v-else-if="filteredTree.length === 0"
          class="text-center"
          :style="{ padding: '40px 8px', fontSize: '12.5px', color: 'var(--ink-3)' }"
        >没有匹配「{{ search }}」的品牌或关键词。</div>

        <div v-for="node in filteredTree" :key="node.task.id" :style="{ marginBottom: '6px' }">
          <!-- 总任务行（品牌）-->
          <div
            class="geo-row flex items-center cursor-pointer"
            :style="{ gap: '9px', padding: '11px 10px', borderRadius: '11px', background: expandedTaskId === node.task.id ? 'var(--card-2)' : 'transparent' }"
            @click="toggleBrand(node.task.id)"
          >
            <!-- 折叠箭头 -->
            <svg
              width="11"
              height="11"
              viewBox="0 0 12 12"
              fill="none"
              stroke="var(--ink-3)"
              stroke-width="1.8"
              stroke-linecap="round"
              :style="{ transform: expandedTaskId === node.task.id ? 'none' : 'rotate(-90deg)', transition: 'transform .18s', flexShrink: 0 }"
            >
              <path d="M2 4l4 4 4-4" />
            </svg>
            <div :style="{ flex: 1, minWidth: 0 }">
              <div class="font-display truncate" :style="{ fontSize: '13.5px', fontWeight: 700 }" :title="node.brand">{{ node.brand }}</div>
              <div :style="{ fontSize: '10.5px', color: 'var(--ink-3)', marginTop: '1px' }">{{ node.keywords.length }} 关键词</div>
            </div>
            <Pill :tone="statusTone(node.task)">{{ statusText(node.task) }}</Pill>
          </div>

          <!-- 运行中进度条（品牌行下）-->
          <div v-if="isRunning(node.task.id)" class="flex items-center" :style="{ gap: '8px', padding: '2px 10px 6px 30px' }">
            <ProgressBar :value="progressRatio(node.task.id)" :height="5" />
            <span
              v-if="monitorStatus.progressOf(node.task.id)"
              class="flex-shrink-0"
              :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }"
            >
              {{ monitorStatus.progressOf(node.task.id)!.current }} /
              {{ monitorStatus.progressOf(node.task.id)!.total }}
            </span>
            <span v-else class="flex-shrink-0" :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }">排队中…</span>
          </div>

          <!-- 子任务行（关键词，仅展开时显示）-->
          <div v-if="expandedTaskId === node.task.id" :style="{ marginTop: '2px', paddingLeft: '8px' }">
            <div
              v-if="node.keywords.length === 0"
              :style="{ padding: '8px 11px', fontSize: '11.5px', color: 'var(--ink-3)' }"
            >此任务未配置关键词 · 编辑任务添加。</div>
            <div
              v-for="k in node.keywords"
              :key="k"
              class="geo-row flex items-center cursor-pointer"
              :style="{
                gap: '8px',
                padding: '9px 11px',
                margin: '2px 0',
                borderRadius: '10px',
                borderLeft: `3px solid ${selectedTaskId === node.task.id && selectedKeyword === k ? 'var(--primary)' : 'transparent'}`,
                background: selectedTaskId === node.task.id && selectedKeyword === k ? 'var(--primary-soft)' : 'transparent',
              }"
              @click="selectKeyword(node.task.id, k)"
            >
              <span
                class="truncate"
                :style="{
                  flex: 1,
                  minWidth: 0,
                  fontSize: '12.5px',
                  fontWeight: selectedTaskId === node.task.id && selectedKeyword === k ? 700 : 500,
                  color: selectedTaskId === node.task.id && selectedKeyword === k ? 'var(--primary-deep)' : 'var(--ink-2)',
                }"
                :title="k"
              >{{ k }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ════════ 右：选中关键词三页签详情 ════════ -->
    <GeoKeywordDetail
      v-if="selectedTask && selectedKeyword"
      :detail="detail"
      :loading="detailLoading"
      :brand="brandOf(selectedTask)"
      :brand-terms="selectedBrandTerms"
      :keyword="selectedKeyword"
      :platform-count="selectedPlatformCount"
      :running="isRunning(selectedTask.id)"
      @run="selectedTask && runNow(selectedTask.id)"
      @cancel="selectedTask && cancelTask(selectedTask.id)"
      @edit="selectedTask && openEditTask(selectedTask)"
      @delete="selectedTask && deleteTask(selectedTask.id)"
    />
    <!-- 无选中关键词（空表 / 选中品牌但无关键词）-->
    <section
      v-else
      class="flex h-full min-h-0 flex-col items-center justify-center overflow-hidden"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }"
    >
      <div class="text-center" :style="{ fontSize: '12.5px', color: 'var(--ink-3)' }">
        {{
          tasks.length === 0
            ? "新建一个卡位任务后，这里展示品牌在各 AI 平台的卡位详情。"
            : "展开左侧品牌、点击一个关键词，查看其概览 / 平台对比 / 竞争·信源。"
        }}
      </div>
    </section>

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
