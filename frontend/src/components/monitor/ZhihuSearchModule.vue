<script setup lang="ts">
/**
 * 知乎搜索排名监控 —— 两级双卡布局（对齐 history/BaiduRankingPage.vue）。
 * L1：左监测任务表 + 右任务详情预览卡。
 * L2：左关键词列表 + 右单关键词排名详情。
 * 数据形状对齐 csm_core/monitor/platforms/zhihu_search.py 的 metric。
 */
import { ref, onMounted, onUnmounted, computed, watch } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { subscribe } from "@/api/client";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import Pill from "@/components/ui/Pill.vue";
import Icon from "@/components/ui/Icon.vue";
import SplitPane from "@/components/ui/SplitPane.vue";
import Dropdown from "@/components/ui/Dropdown.vue";
import LineChart from "./history/LineChart.vue";
import AddTaskModal from "./AddTaskModal.vue";
import { zhihuSearchTaskStatus } from "@/utils/zhihuSearchStatus";
import { batchZhihuSearchKpis } from "@/utils/monitor-zhihu-kpi";

interface ResultItem {
  rank: number; title: string; content_type: string; url: string;
  voteup_count: number; author_name: string;
  matches_brand: boolean; matched_brand: string | null; matched_field: string | null;
  fulltext_status?: string; excerpt: string;
}
interface KeywordResult {
  keyword: string; results: ResultItem[]; matched_count: number;
  first_rank: number; result_count: number;
  empty_reason: string | null; api_code: number | null; fetch_error: string | null;
}
interface ResultRow { task_id: number; checked_at: string; status: string; rank: number; metric: any; }
interface Task {
  id: number; type: string; name: string; target_url: string;
  enabled: boolean; schedule_cron: string;
  last_check_at: string | null; last_status: string | null;
  config?: Record<string, any>;
}

const sidecar = useSidecar();
const monitorStatus = useMonitorStatus();
const toast = useToast();

const tasks = ref<Task[]>([]);
const selectedId = ref<number | null>(null);        // L2 entry; null = L1 landing
const previewId = ref<number | null>(null);          // L1 right-card preview target
const selectedKeywordIdx = ref<number | null>(null); // L2 selected keyword
const taskHistories = ref<Record<number, ResultRow[]>>({}); // per-task recent history (L1 status + preview trend)
const latestMetric = ref<Record<string, any> | null>(null); // selected task latest metric (L2)
const latestStatus = ref<string | null>(null);
const taskResults = ref<ResultRow[]>([]);            // selected task history (kept for SSE reload parity)
const loadFailed = ref(false);
const showModal = ref(false);
const editingTask = ref<Task | null>(null);

const selectedTask = computed(() => tasks.value.find((t) => t.id === selectedId.value) ?? null);
const previewTask = computed<Task | null>(() => {
  if (previewId.value !== null) {
    const t = tasks.value.find((x) => x.id === previewId.value);
    if (t) return t;
  }
  return tasks.value[0] ?? null;
});
const previewKpis = computed(() => {
  const t = previewTask.value;
  if (!t) return null;
  const kws = (taskHistories.value[t.id]?.[0]?.metric?.keywords ?? []) as Array<{ matched_count?: number; first_rank?: number }>;
  return batchZhihuSearchKpis(kws.map((k) => ({ matched_count: k.matched_count ?? 0, first_rank: k.first_rank ?? 0 })));
});
const keywordResults = computed<KeywordResult[]>(() => latestMetric.value?.keywords ?? []);
const currentKeyword = computed<KeywordResult | null>(() =>
  selectedKeywordIdx.value === null ? null : keywordResults.value[selectedKeywordIdx.value] ?? null,
);
const fulltextNoCookie = computed(() =>
  keywordResults.value.some((kw) => kw.results?.some((r) => r.fulltext_status === "no_cookie")),
);

function statusOf(t: Task) {
  return zhihuSearchTaskStatus(taskHistories.value[t.id]?.[0] ?? null);
}
function isRunning(id: number) { return monitorStatus.isRunning(id); }
const taskProgress = computed(() => monitorStatus.taskProgress);

// 该关键词的知乎搜索结果页 URL（右卡「知乎搜索页」链接跳转 —— 按当前选中关键词派生，
// 不再用任务级 target_url，那只由首个关键词派生）。
function keywordSearchUrl(kw: string): string {
  return `https://www.zhihu.com/search?type=content&q=${encodeURIComponent(kw)}`;
}

// ── L2 单关键词详情 helpers（镜像知乎问题右卡）──
// 选中关键词近 7 天「卡位数量(matched_count)」趋势 —— 从任务历史每天取该关键词的 matched_count
const selectedKwTrend = computed<Array<{ iso: string; label: string; matched: number | null }>>(() => {
  const out: Array<{ iso: string; label: string; matched: number | null }> = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ iso, label: String(d.getDate()), matched: null });
  }
  const kwName = currentKeyword.value?.keyword;
  if (!kwName) return out;
  const placed = new Set<string>();
  for (const r of taskResults.value) {
    const d = new Date(r.checked_at);
    if (Number.isNaN(d.getTime())) continue;
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (placed.has(iso)) continue;
    const bucket = out.find((b) => b.iso === iso);
    if (bucket) {
      const kw = (r.metric?.keywords ?? []).find((k: any) => k.keyword === kwName);
      bucket.matched = kw ? Number(kw.matched_count) || 0 : 0;
      placed.add(iso);
    }
  }
  return out;
});
const selectedKwTrendLabels = computed(() => selectedKwTrend.value.map((b) => b.label));
const selectedKwTrendData = computed(() => selectedKwTrend.value.map((b) => b.matched));
const hasSelectedKwTrend = computed(() => selectedKwTrend.value.some((b) => b.matched !== null));

// ── data loading ──
async function loadTasks() {
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: "zhihu_search" } });
    tasks.value = r.data.tasks ?? [];
    loadFailed.value = false;
    if (previewId.value === null && tasks.value.length) previewId.value = tasks.value[0].id;
    void loadAllTaskHistories();
  } catch (e: any) {
    loadFailed.value = true;
    if (e?.response?.status !== 503) toast.error(`加载失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}
async function loadAllTaskHistories() {
  await Promise.all(tasks.value.map((t) => loadTaskHistory(t.id)));
}
async function loadTaskHistory(id: number) {
  try {
    const r = await sidecar.client.get("/api/monitor/results", { params: { task_id: id, limit: 14 } });
    taskHistories.value = { ...taskHistories.value, [id]: r.data.results ?? [] };
  } catch {
    taskHistories.value = { ...taskHistories.value, [id]: [] };
  }
}
async function loadLatest(id: number) {
  try {
    const r = await sidecar.client.get("/api/monitor/results", { params: { task_id: id, limit: 30 } });
    const rows = r.data.results ?? [];
    taskResults.value = rows;
    latestMetric.value = rows.length ? rows[0].metric ?? null : null;
    latestStatus.value = rows.length ? rows[0].status ?? null : null;
  } catch {
    taskResults.value = []; latestMetric.value = null; latestStatus.value = null;
  }
}

// ── navigation ──
async function enterDetail(id: number) {
  selectedKeywordIdx.value = null;
  await loadLatest(id);
  selectedId.value = id;
}
function backToList() { selectedId.value = null; selectedKeywordIdx.value = null; }

// ── actions ──
async function runNowTask(id: number) {
  monitorStatus.markRunning(id);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${id}/run-now`, {});
  } catch (e: any) {
    monitorStatus.clearRunning(id);
    toast.error(`触发失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}
async function cancelTask(id: number) {
  try {
    const ok = await monitorStatus.cancel(id);
    if (ok) toast.info("已请求停止…"); else toast.warn("没有可停止的任务");
  } catch (e: any) {
    toast.error(`停止失败：${e?.message ?? e}`);
  }
}
async function removeTask(id: number) {
  if (!(await confirmDialog("确认删除这个知乎搜索监控任务？", { title: "删除监测任务" }))) return;
  try {
    await sidecar.client.delete(`/api/monitor/tasks/${id}`);
    toast.success("已删除");
    if (selectedId.value === id) backToList();
    if (previewId.value === id) previewId.value = null;
    await loadTasks();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}
function openAdd() { editingTask.value = null; showModal.value = true; }
function openEdit(t: Task) { editingTask.value = t; showModal.value = true; }
function openSchedule() { if (previewTask.value) openEdit(previewTask.value); }
async function onTaskSaved() {
  showModal.value = false;
  await loadTasks();
  if (selectedId.value !== null) await loadLatest(selectedId.value);
}

// ── 导出预览任务各关键词命中条数 CSV ──
function exportPreviewCsv() {
  const t = previewTask.value;
  if (!t) { toast.warn("没有选中的任务"); return; }
  const kws = taskHistories.value[t.id]?.[0]?.metric?.keywords;
  if (!Array.isArray(kws) || kws.length === 0) { toast.warn("该任务还没有可导出的结果，请先执行一次"); return; }
  const rows = ["关键词,命中条数,首位排名"];
  for (const kw of kws) {
    const name = `"${String(kw.keyword || "").replace(/"/g, '""')}"`;
    const rank = Number(kw.first_rank) > 0 ? kw.first_rank : "";
    rows.push(`${name},${Number(kw.matched_count) || 0},${rank}`);
  }
  const blob = new Blob(["﻿" + rows.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `${t.name}-知乎命中-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast.success(`已导出 ${kws.length} 条关键词`);
}

// ── SSE + lifecycle ──
let stopSSE: (() => void) | null = null;
onMounted(async () => {
  await loadTasks();
  void monitorStatus.hydrate();
  stopSSE = subscribe("/api/monitor/events", {
    finished: async (d: any) => {
      if (typeof d?.task_id === "number") { monitorStatus.clearRunning(d.task_id); void loadTaskHistory(d.task_id); }
      await loadTasks();
      if (selectedId.value !== null && d?.task_id === selectedId.value) await loadLatest(selectedId.value);
    },
    failed: async (d: any) => {
      if (typeof d?.task_id === "number") monitorStatus.clearRunning(d.task_id);
      await loadTasks();
    },
  });
});
onUnmounted(() => { if (stopSSE) stopSSE(); });

// 进 L2 自动选第一个关键词
watch(keywordResults, (kws) => {
  if (kws.length > 0 && selectedKeywordIdx.value === null) selectedKeywordIdx.value = 0;
});
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">

    <!-- ═══ 单一 SplitPane：#left 按 selectedId 切换 L1/L2；#right 同理 ═══ -->
    <SplitPane>
      <template #left>
        <section class="flex h-full min-h-0 flex-col overflow-hidden" :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }">

          <!-- ── L1 左：监测任务列表 ── -->
          <template v-if="selectedId === null">
            <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
              <div class="font-display text-[14px] font-semibold">监测任务</div>
              <button type="button" class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium" :style="{ background: 'var(--primary)', color: '#fff', borderRadius: '999px' }" @click="openAdd">
                <Icon name="plus" :size="12" /><span>新增任务</span>
              </button>
            </div>
            <!-- L1 列头：3 列 -->
            <div class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase" :style="{ gridTemplateColumns: '1.5fr .9fr 1.1fr', letterSpacing: '1.2px', color: 'var(--ink-3)', borderBottom: '1px solid var(--line)' }">
              <div>任务名字</div><div class="text-center">状态</div><div class="text-center">操作</div>
            </div>
            <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <div v-if="loadFailed" class="py-10 text-center text-[12px]" :style="{ color: 'var(--red, #d85a48)' }">
                任务列表加载失败。<button type="button" class="underline" @click="loadTasks()">重试</button>
              </div>
              <div v-else-if="!tasks.length" class="flex flex-1 flex-col items-center justify-center gap-1 py-16">
                <div class="text-[13px] font-medium" :style="{ color: 'var(--ink-2)' }">暂无知乎搜索任务</div>
                <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">点击右上「新增任务」开始监测</div>
              </div>
              <template v-else>
                <!-- L1 任务行：3 列，Col1=名字+副标题，Col2=状态，Col3=⋯菜单 -->
                <div v-for="(t, i) in tasks" :key="t.id" class="grid cursor-pointer items-center transition"
                  :style="{ gridTemplateColumns: '1.5fr .9fr 1.1fr', background: previewId === t.id ? 'var(--card-2)' : 'transparent', borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none', padding: '14px 8px', borderRadius: '10px' }"
                  @mouseenter="(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                  @mouseleave="(e) => { if (previewId !== t.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
                  @click="previewId = t.id">
                  <!-- Col 1: 任务名（钻入）+ 副标题 -->
                  <div class="min-w-0">
                    <button type="button" class="truncate text-[13px] font-medium text-left w-full" :style="{ color: 'var(--primary-deep)', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }" @click.stop="enterDetail(t.id)">{{ t.name }}</button>
                    <div class="truncate text-[11px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                      {{ t.config?.search_keywords?.length ?? 0 }} 个关键词 · 品牌 {{ t.config?.target_brand || '—' }}
                    </div>
                  </div>
                  <!-- Col 2: 状态 Pill（运行中显示进度条） -->
                  <div class="flex flex-col items-center gap-1">
                    <template v-if="isRunning(t.id)">
                      <div class="text-[11.5px] font-medium" :style="{ color: 'var(--primary-deep)' }">{{ taskProgress[t.id]?.current ?? 0 }} / {{ taskProgress[t.id]?.total ?? (t.config?.search_keywords?.length ?? 0) }}</div>
                      <div :style="{ width: '80%', height: '4px', background: 'var(--card-2)', borderRadius: '999px', overflow: 'hidden' }">
                        <div :style="{ height: '100%', width: (taskProgress[t.id]?.total ? Math.min(100, Math.round((taskProgress[t.id]!.current / Math.max(1, taskProgress[t.id]!.total)) * 100)) : 0) + '%', background: 'var(--primary-deep)', transition: 'width 0.3s ease' }" />
                      </div>
                    </template>
                    <Pill v-else :tone="statusOf(t).tone">{{ statusOf(t).label }}</Pill>
                  </div>
                  <!-- Col 3: ⋯ Dropdown -->
                  <div class="flex items-center justify-center">
                    <Dropdown
                      :items="[
                        isRunning(t.id)
                          ? { key: 'stop', label: '停止监测', icon: 'x' }
                          : { key: 'run', label: '立刻监测', icon: 'play' },
                        { key: 'edit', label: '编辑任务', icon: 'edit' },
                        { key: 'delete', label: '删除任务', icon: 'trash', tone: 'danger' },
                      ]"
                      align="right"
                      @select="(key) => {
                        if (key === 'run') runNowTask(t.id);
                        else if (key === 'stop') cancelTask(t.id);
                        else if (key === 'edit') openEdit(t);
                        else if (key === 'delete') removeTask(t.id);
                      }"
                    >
                      <template #trigger>
                        <button
                          type="button"
                          class="inline-flex h-7 w-7 items-center justify-center"
                          :style="{ borderRadius: '999px', color: 'var(--ink-3)', cursor: 'pointer' }"
                          title="更多操作"
                          @click.stop
                        >
                          <Icon name="more" :size="15" />
                        </button>
                      </template>
                    </Dropdown>
                  </div>
                </div>
              </template>
            </div>
          </template>

          <!-- ── L2 左：面包屑 + 3 状态条 + 关键词列表 ── -->
          <template v-else>
            <!-- 面包屑 -->
            <div class="mb-3 flex-shrink-0 flex items-start gap-3">
              <button type="button" class="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center" :style="{ background: 'var(--card-2)', border: '1px solid var(--line)', borderRadius: '999px', color: 'var(--ink-2)', cursor: 'pointer' }" title="返回任务列表" @click="backToList()"><Icon name="arrowLeft" :size="14" /></button>
              <div class="min-w-0 flex-1">
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">知乎搜索 · 关键词列表</div>
                <div class="font-display text-[14px] font-semibold mt-0.5">{{ selectedTask?.name ?? '' }}</div>
              </div>
            </div>

            <!-- 知乎特有状态条（3 条全部保留） -->
            <div v-if="latestStatus === 'error'" class="mb-2 flex-shrink-0 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--red, #d85a48)' }"><Pill tone="alert">鉴权失败</Pill>检查设置页知乎 Access Secret 或系统时钟。</div>
            <div v-if="latestStatus === 'risk_control'" class="mb-2 flex-shrink-0 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-2)' }"><Pill tone="warn">频率限制</Pill>被知乎频率/配额限制（30001），稍后重试。</div>
            <div v-if="fulltextNoCookie" class="mb-2 flex-shrink-0 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-2)' }"><Pill tone="warn">全文匹配未生效</Pill>已开启全文匹配但未配置知乎 Cookie，请到 Cookie 管理添加。</div>

            <!-- L2 列头：2 列 -->
            <div class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase" :style="{ gridTemplateColumns: '1.6fr 1fr', letterSpacing: '1.2px', color: 'var(--ink-3)', borderBottom: '1px solid var(--line)' }">
              <div>关键词</div><div class="text-center">状态</div>
            </div>
            <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <div v-if="!keywordResults.length" class="py-10 text-center text-[12px]" :style="{ color: 'var(--ink-3)' }">还没有结果，点右下「启动监测」。</div>
              <!-- L2 关键词行：2 列，只读（无操作菜单） -->
              <div v-for="(kw, i) in keywordResults" :key="kw.keyword + '-' + i" class="grid items-center cursor-pointer transition"
                :style="{ gridTemplateColumns: '1.6fr 1fr', borderBottom: i < keywordResults.length - 1 ? '1px solid var(--line)' : 'none', padding: '12px 8px', background: selectedKeywordIdx === i ? 'var(--card-2)' : 'transparent' }"
                @click="selectedKeywordIdx = i"
                @mouseenter="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                @mouseleave="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'transparent'; }">
                <!-- Col 1: 关键词 + 副标题（卡位 · 首位） -->
                <div class="min-w-0">
                  <div class="truncate text-[12.5px] font-medium" :style="{ color: 'var(--ink)' }">{{ kw.keyword }}</div>
                  <div class="truncate text-[11px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                    卡位 {{ kw.matched_count }} · 首位 {{ kw.first_rank > 0 ? '#' + kw.first_rank : '—' }}
                  </div>
                </div>
                <!-- Col 2: 状态 Pill -->
                <div class="text-center">
                  <Pill v-if="kw.fetch_error" tone="alert">失败</Pill>
                  <Pill v-else-if="kw.first_rank > 0" tone="ok">命中</Pill>
                  <Pill v-else tone="info">未命中</Pill>
                </div>
              </div>
            </div>
          </template>

        </section>
      </template>

      <template #right>
        <section class="flex h-full min-h-0 flex-col overflow-hidden" :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }">

          <!-- ── L1 右：任务汇总（KPI 四联 + 关键词速览 + 导出/定时）── -->
          <template v-if="selectedId === null">
            <div v-if="!previewTask" class="flex flex-1 flex-col items-center justify-center text-center" :style="{ color: 'var(--ink-3)' }">
              <div class="text-[14px] font-medium mb-1">暂无任务</div>
              <div class="text-[11.5px]">点击左上「新增任务」开始监测</div>
            </div>
            <template v-else>
              <!-- 标题 -->
              <div class="mb-3 flex-shrink-0">
                <div class="font-display text-[14px] font-semibold">{{ previewTask.name }}</div>
                <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">任务汇总</div>
              </div>

              <!-- 滚动区 -->
              <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">

                <!-- KPI 四联 -->
                <div class="grid grid-cols-2 gap-3">
                  <!-- 关键词数 -->
                  <div :style="{ padding: '12px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
                    <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">关键词数</div>
                    <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                      {{ previewTask.config?.search_keywords?.length ?? previewKpis?.total ?? 0 }}
                    </div>
                  </div>
                  <!-- 目标品牌 -->
                  <div :style="{ padding: '12px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
                    <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">目标品牌</div>
                    <div class="font-display mt-1 font-bold" :style="{ fontSize: '16px' }">
                      {{ previewTask.config?.target_brand || '—' }}
                    </div>
                  </div>
                  <!-- 命中关键词数 -->
                  <div :style="{ padding: '12px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
                    <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">命中关键词数</div>
                    <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                      <template v-if="previewKpis">
                        {{ previewKpis.hitKeywords }}<span :style="{ color: 'var(--ink-3)', fontSize: '13px' }">/{{ previewKpis.total }}</span>
                      </template>
                      <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                    </div>
                  </div>
                  <!-- 最佳首位 -->
                  <div :style="{ padding: '12px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
                    <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">最佳首位</div>
                    <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                      <template v-if="previewKpis?.bestFirstRank != null">
                        #{{ previewKpis.bestFirstRank }}
                      </template>
                      <span v-else :style="{ color: 'var(--ink-3)', fontSize: '14px' }">—</span>
                    </div>
                  </div>
                </div>

                <!-- 关键词速览表 -->
                <div>
                  <div class="mb-2 text-[10.5px] uppercase" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">关键词速览</div>
                  <div :style="{ borderRadius: '10px', border: '1px solid var(--line)', overflow: 'hidden' }">
                    <!-- 表头 -->
                    <div
                      class="grid text-[10.5px]"
                      :style="{ gridTemplateColumns: '1fr 44px 52px', padding: '5px 10px', background: 'var(--card-2)', color: 'var(--ink-3)', borderBottom: '1px solid var(--line)' }"
                    >
                      <span>关键词</span>
                      <span :style="{ textAlign: 'right' }">卡位</span>
                      <span :style="{ textAlign: 'right' }">首位</span>
                    </div>
                    <!-- 空态 -->
                    <div
                      v-if="!(taskHistories[previewTask.id]?.[0]?.metric?.keywords ?? []).length"
                      class="text-[11.5px] italic"
                      :style="{ padding: '8px 10px', color: 'var(--ink-3)' }"
                    >尚无检测数据</div>
                    <!-- 数据行 -->
                    <div
                      v-for="kw in (taskHistories[previewTask.id]?.[0]?.metric?.keywords ?? [])"
                      :key="kw.keyword"
                      class="grid text-[11.5px]"
                      :style="{ gridTemplateColumns: '1fr 44px 52px', padding: '6px 10px', borderBottom: '1px solid var(--line)', color: 'var(--ink-2)' }"
                    >
                      <span class="truncate pr-2" :title="kw.keyword" :style="{ color: 'var(--ink)' }">{{ kw.keyword }}</span>
                      <span :style="{ textAlign: 'right' }">{{ kw.matched_count }}</span>
                      <span :style="{ textAlign: 'right' }">
                        <template v-if="kw.first_rank > 0">#{{ kw.first_rank }}</template>
                        <span v-else :style="{ color: 'var(--ink-3)', fontSize: '10.5px' }">—</span>
                      </span>
                    </div>
                  </div>
                </div>

                <!-- 导出数据 / 定时监测 -->
                <div class="flex flex-shrink-0 gap-2">
                  <button type="button" class="flex-1 text-[12.5px] font-medium" :style="{ padding: '9px 14px', background: 'var(--card-2)', border: '1px solid var(--line)', borderRadius: '8px', color: 'var(--ink-2)', cursor: 'pointer' }" @click="exportPreviewCsv()">导出数据</button>
                  <button type="button" class="flex-1 text-[12.5px] font-medium" :style="{ padding: '9px 14px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer' }" @click="openSchedule()">定时监测</button>
                </div>

              </div>
            </template>
          </template>

          <!-- ── L2 右：单关键词详情（镜像知乎问题右卡，原样 re-parent）── -->
          <template v-else>
            <div v-if="!currentKeyword" class="flex flex-1 flex-col items-center justify-center text-center" :style="{ color: 'var(--ink-3)' }">
              <div class="text-[14px] font-medium mb-1">选择左侧关键词</div>
              <div class="text-[11.5px]">查看该关键词的卡位详情</div>
            </div>
            <template v-else>
              <!-- 标题：关键词（搜索词）-->
              <div class="mb-3 flex-shrink-0 flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="font-display text-[14px] font-semibold truncate" :title="currentKeyword.keyword">{{ currentKeyword.keyword }}</div>
                  <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">关键词详情</div>
                </div>
                <a
                  :href="keywordSearchUrl(currentKeyword.keyword)"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex flex-shrink-0 items-center gap-1 px-3 py-1.5 text-[11.5px]"
                  :style="{ background: 'var(--card-2)', color: 'var(--ink-2)', border: '1px solid var(--line)', borderRadius: '999px', textDecoration: 'none' }"
                  title="在浏览器打开该关键词的知乎搜索页"
                >
                  <Icon name="external" :size="12" />
                  <span>知乎搜索页</span>
                </a>
              </div>

              <!-- KPI：卡位数量 / 最高排名（自家命中数 = 卡位数量 matched_count 同值，QA 已确认去重） -->
              <div class="mb-4 grid flex-shrink-0 grid-cols-2 gap-3">
                <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '12px', border: '1px solid var(--line)' }">
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">卡位数量</div>
                  <div class="font-display mt-1 font-bold text-[20px]">
                    <template v-if="currentKeyword.matched_count > 0">{{ currentKeyword.matched_count }}</template>
                    <span v-else :style="{ color: 'var(--red, #d85a48)', fontSize: '14px' }">前 10 以外</span>
                  </div>
                </div>
                <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '12px', border: '1px solid var(--line)' }">
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">最高排名</div>
                  <div class="font-display mt-1 font-bold text-[20px]">
                    <template v-if="currentKeyword.first_rank > 0">#{{ currentKeyword.first_rank }}</template>
                    <span v-else :style="{ color: 'var(--ink-3)', fontSize: '14px' }">未上榜</span>
                  </div>
                </div>
              </div>

              <!-- 最近 7 天卡位趋势 -->
              <div class="mb-4 flex-shrink-0">
                <div class="mb-2 text-[12px] font-semibold">最近 7 天卡位趋势</div>
                <LineChart v-if="hasSelectedKwTrend" :labels="selectedKwTrendLabels" :series="[{ label: '卡位数量', color: 'var(--primary-deep, #c9521f)', data: selectedKwTrendData }]" :y-max="10" />
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">无历史数据 —— 跑几次「启动监测」后会成线。</div>
              </div>

              <!-- 状态提示 -->
              <div v-if="currentKeyword.fetch_error" class="text-[11.5px] mb-2 px-3 py-2 rounded" :style="{ background: 'rgba(239,68,68,0.08)', color: 'var(--red-deep)', borderLeft: '3px solid var(--red-deep)' }">抓取失败：{{ currentKeyword.fetch_error.slice(0, 120) }}</div>
              <div v-else-if="currentKeyword.empty_reason" class="text-[11.5px] mb-2" :style="{ color: 'var(--ink-3)' }">知乎无结果：{{ currentKeyword.empty_reason }}</div>

              <!-- 前 10 排名列表（固定高度滚动卡片）-->
              <div class="min-h-0 flex-1 overflow-y-auto">
                <div class="mb-2 flex items-center justify-between">
                  <div class="text-[12px] font-semibold">前 10 结果</div>
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">自家命中 <span :style="{ color: 'var(--primary-deep)', fontWeight: 600 }">{{ currentKeyword.matched_count }}</span> 条</div>
                </div>
                <template v-if="currentKeyword.results.length">
                  <div v-for="r in currentKeyword.results" :key="r.rank" class="mb-1.5 flex items-start gap-3" :style="{ padding: '10px', borderRadius: '10px', background: r.matches_brand ? 'var(--primary-soft)' : 'var(--card-2)', border: '1px solid ' + (r.matches_brand ? 'rgba(238,106,42,0.3)' : 'var(--line)') }">
                    <span class="font-display text-[13px] font-bold flex-shrink-0" :style="{ width: '24px', color: r.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)' }">#{{ r.rank }}</span>
                    <div class="min-w-0 flex-1">
                      <a :href="r.url" target="_blank" rel="noopener" class="block truncate text-[12.5px] font-medium hover:underline" :style="{ color: 'var(--ink)', textDecoration: 'none' }" :title="r.title">{{ r.title }}</a>
                      <div class="mt-0.5 flex items-center gap-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                        <span class="flex-shrink-0 px-1.5 rounded" :style="{ background: 'var(--card)', border: '1px solid var(--line)' }">{{ (r.content_type || '').toLowerCase() === 'article' ? '专栏' : (r.content_type || '').toLowerCase() === 'answer' ? '回答' : (r.content_type || '其他') }}</span>
                        <span class="truncate">{{ r.author_name || '—' }}</span>
                        <span v-if="r.voteup_count" class="flex-shrink-0">▲ {{ r.voteup_count }}</span>
                        <span v-if="r.matches_brand" class="ml-auto flex-shrink-0" :style="{ color: 'var(--primary-deep)', fontWeight: 600 }">自家<template v-if="r.matched_field === 'fulltext'"> · 正文</template></span>
                      </div>
                    </div>
                  </div>
                </template>
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">还没有结果，点下方「启动监测」。</div>
              </div>

              <!-- 底部：启动监测 -->
              <div class="mt-4 flex-shrink-0">
                <button type="button" class="w-full font-medium text-[14px]" :disabled="isRunning(selectedId!)" :style="{ padding: '12px 24px', borderRadius: '10px', background: isRunning(selectedId!) ? 'var(--card-2)' : 'var(--primary-deep)', color: isRunning(selectedId!) ? 'var(--ink-3)' : '#fff', cursor: isRunning(selectedId!) ? 'not-allowed' : 'pointer', border: 'none' }" @click="runNowTask(selectedId!)">{{ isRunning(selectedId!) ? '监测中…' : '▶ 启动监测' }}</button>
              </div>
            </template>
          </template>

        </section>
      </template>
    </SplitPane>

    <AddTaskModal v-model:open="showModal" :default-type="'zhihu_search' as any" :editing-task="editingTask as any" @created="onTaskSaved" @updated="onTaskSaved" />
  </div>
</template>
