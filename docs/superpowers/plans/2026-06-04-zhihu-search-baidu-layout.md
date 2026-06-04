# 知乎搜索对齐百度排名两级布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把知乎搜索监控（`ZhihuSearchModule.vue`）从单级布局改为与百度排名一致的两级双卡布局（L1 任务表+预览卡 / L2 关键词列表+单关键词详情）。

**Architecture:** 纯前端，镜像 `history/BaiduRankingPage.vue` 的两级结构进 `ZhihuSearchModule.vue`，保持独立组件、不抽共享组件、不改 sidecar。状态算法抽成可测 util。数据形状不变（对齐 `csm_core/monitor/platforms/zhihu_search.py` 的 metric）。

**Tech Stack:** Vue 3 `<script setup lang="ts">`、Pinia（`useSidecar`/`useMonitorStatus`）、vitest、既有组件 `Pill`/`Icon`/`LineChart`/`AddTaskModal`。

**验证环境：** browser-dev（http://localhost:5173 → 监测中心 → 知乎搜索）。前端改动 vite 自动热更，**不重启 sidecar**。

---

## File Structure

- **Create** `frontend/src/utils/zhihuSearchStatus.ts` — L1 状态列纯函数（可测，单一职责）。
- **Create** `frontend/src/utils/__tests__/zhihuSearchStatus.spec.ts` — vitest。
- **Rewrite** `frontend/src/components/monitor/ZhihuSearchModule.vue` — 单级 → 两级双卡（script + template 整体重写；复用现有 load/run/SSE 逻辑）。
- **Unchanged** `frontend/src/views/MonitorView.vue` — `<ZhihuSearchModule />` 挂载点不动。

---

## Task 1: 状态算法 util（TDD）

**Files:**
- Create: `frontend/src/utils/zhihuSearchStatus.ts`
- Test: `frontend/src/utils/__tests__/zhihuSearchStatus.spec.ts`

规则（来自 spec）：无历史→未跑；`status==='error'`→鉴权失败(alert)；`status==='risk_control'`→限频(warn)；metric 任一关键词 `first_rank>0`→正常(ok)；全部前 10 无命中→未命中(info)；空 keywords→未跑。

- [ ] **Step 1: Write the failing test**

`frontend/src/utils/__tests__/zhihuSearchStatus.spec.ts`:
```ts
import { describe, it, expect } from "vitest";
import { zhihuSearchTaskStatus } from "../zhihuSearchStatus";

describe("zhihuSearchTaskStatus", () => {
  it("无历史 → 未跑", () => {
    expect(zhihuSearchTaskStatus(null)).toEqual({ label: "未跑", tone: "info" });
  });
  it("error → 鉴权失败", () => {
    expect(zhihuSearchTaskStatus({ status: "error", metric: {} })).toEqual({ label: "鉴权失败", tone: "alert" });
  });
  it("risk_control → 限频", () => {
    expect(zhihuSearchTaskStatus({ status: "risk_control", metric: {} })).toEqual({ label: "限频", tone: "warn" });
  });
  it("任一关键词 first_rank>0 → 正常", () => {
    expect(zhihuSearchTaskStatus({ status: "ok", metric: { keywords: [{ first_rank: -1 }, { first_rank: 3 }] } }))
      .toEqual({ label: "正常", tone: "ok" });
  });
  it("全部前 10 无命中 → 未命中", () => {
    expect(zhihuSearchTaskStatus({ status: "ok", metric: { keywords: [{ first_rank: -1 }, { first_rank: 0 }] } }))
      .toEqual({ label: "未命中", tone: "info" });
  });
  it("空 keywords → 未跑", () => {
    expect(zhihuSearchTaskStatus({ status: "ok", metric: { keywords: [] } })).toEqual({ label: "未跑", tone: "info" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/utils/__tests__/zhihuSearchStatus.spec.ts`
Expected: FAIL — `Failed to resolve import "../zhihuSearchStatus"`.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/utils/zhihuSearchStatus.ts`:
```ts
export type ZhihuSearchTone = "ok" | "warn" | "alert" | "info";
export interface ZhihuSearchStatus {
  label: string;
  tone: ZhihuSearchTone;
}

/**
 * L1「状态」列 —— 基于该任务最新一份 result（taskHistories[id][0]）。
 * latest 形如 { status, metric }；null/undefined = 无历史。
 */
export function zhihuSearchTaskStatus(
  latest: { status?: string | null; metric?: any } | null | undefined,
): ZhihuSearchStatus {
  if (!latest) return { label: "未跑", tone: "info" };
  if (latest.status === "error") return { label: "鉴权失败", tone: "alert" };
  if (latest.status === "risk_control") return { label: "限频", tone: "warn" };
  const kws = latest.metric?.keywords;
  if (!Array.isArray(kws) || kws.length === 0) return { label: "未跑", tone: "info" };
  const anyHit = kws.some((k: any) => Number(k?.first_rank) > 0);
  return anyHit ? { label: "正常", tone: "ok" } : { label: "未命中", tone: "info" };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npx vitest run src/utils/__tests__/zhihuSearchStatus.spec.ts`
Expected: PASS — 6 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/zhihuSearchStatus.ts frontend/src/utils/__tests__/zhihuSearchStatus.spec.ts
git commit -m "feat(monitor-ui): zhihu_search L1 状态算法 util + 测试"
```

---

## Task 2: 重写 ZhihuSearchModule 为两级双卡

**Files:**
- Rewrite: `frontend/src/components/monitor/ZhihuSearchModule.vue`

整体替换 `<script setup>` 与 `<template>`。沿用现有数据接口（`/api/monitor/tasks?type=zhihu_search`、`/api/monitor/results?task_id`、`/api/monitor/tasks/{id}/run-now`、SSE `/api/monitor/events`）。新增：`previewId`（L1 预览）、`selectedKeywordIdx`（L2 选中）、`taskHistories` 每任务历史 fan-out（L1 状态+预览趋势）、`enterDetail`/`backToList`、`exportPreviewCsv`、`openSchedule`，并用 Task 1 的 `zhihuSearchTaskStatus`。**默认行为改为停在 L1**（`previewId=第一条`，不再自动 `selectTask`）。

- [ ] **Step 1: 替换 `<script setup>`**

把 `ZhihuSearchModule.vue` 的整个 `<script setup lang="ts"> ... </script>` 替换为：

```vue
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
import LineChart from "./history/LineChart.vue";
import AddTaskModal from "./AddTaskModal.vue";
import { zhihuSearchTaskStatus } from "@/utils/zhihuSearchStatus";

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

// ── L1 预览卡近 7 天趋势（命中关键词数 + 最优排名），基于 previewTask 历史 ──
const RANK_SENTINEL = 15;
function buildTrend(history: ResultRow[]) {
  const out: Array<{ iso: string; label: string; matched: number | null; rank: number | null }> = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ iso, label: String(d.getDate()), matched: null, rank: null });
  }
  const placed = new Set<string>();
  for (const r of history) { // history desc（最新在前）
    const d = new Date(r.checked_at);
    if (Number.isNaN(d.getTime())) continue;
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (placed.has(iso)) continue;
    const bucket = out.find((b) => b.iso === iso);
    if (bucket) {
      bucket.matched = Number(r.metric?.matched_keywords ?? 0);
      const rk = Number(r.rank ?? -1);
      bucket.rank = rk > 0 ? rk : RANK_SENTINEL;
      placed.add(iso);
    }
  }
  return out;
}
const previewTrend = computed(() => buildTrend(taskHistories.value[previewTask.value?.id ?? -1] ?? []));
const hasPreviewTrend = computed(() => previewTrend.value.some((b) => b.matched !== null));
const previewTrendLabels = computed(() => previewTrend.value.map((b) => b.label));
const previewTrendMatched = computed(() => previewTrend.value.map((b) => b.matched));
const previewTrendRank = computed(() => previewTrend.value.map((b) => b.rank));
const TREND_MATCHED_COLOR = "#c9521f";
const TREND_RANK_COLOR = "#8a8580";

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
```

- [ ] **Step 2: 替换 `<template>`**

把整个 `<template> ... </template>` 替换为：

```vue
<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">

    <!-- ═══ L1: 落地页 selectedId===null ═══ -->
    <template v-if="selectedId === null">
      <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">

        <!-- 左卡：监测任务 -->
        <section class="flex min-h-0 flex-col" :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }">
          <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
            <div class="font-display text-[14px] font-semibold">监测任务</div>
            <button type="button" class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium" :style="{ background: 'var(--primary)', color: '#fff', borderRadius: '999px' }" @click="openAdd">
              <Icon name="plus" :size="12" /><span>新增任务</span>
            </button>
          </div>
          <div class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase" :style="{ gridTemplateColumns: '1.6fr .85fr .85fr 1fr', letterSpacing: '1.2px', color: 'var(--ink-3)', borderBottom: '1px solid var(--line)' }">
            <div>任务名字</div><div class="text-center">变化</div><div class="text-center">状态</div><div class="text-center">操作</div>
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
              <div v-for="(t, i) in tasks" :key="t.id" class="grid cursor-pointer items-center transition"
                :style="{ gridTemplateColumns: '1.6fr .85fr .85fr 1fr', background: previewId === t.id ? 'var(--card-2)' : 'transparent', borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none', padding: '14px 8px', borderRadius: '10px' }"
                @mouseenter="(e) => { previewId = t.id; (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                @mouseleave="(e) => { if (previewId !== t.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
                @click="previewId = t.id">
                <div class="min-w-0">
                  <button type="button" class="truncate text-[13px] font-medium text-left w-full" :style="{ color: 'var(--primary-deep)', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }" @click.stop="enterDetail(t.id)">{{ t.name }}</button>
                  <div class="truncate text-[11px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                    {{ t.config?.search_keywords?.length ?? 0 }} 个关键词<template v-if="t.config?.target_brand"> · 品牌 {{ t.config.target_brand }}</template>
                  </div>
                </div>
                <div class="text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
                <div class="flex flex-col items-center gap-1">
                  <template v-if="isRunning(t.id)">
                    <div class="text-[11.5px] font-medium" :style="{ color: 'var(--primary-deep)' }">{{ taskProgress[t.id]?.current ?? 0 }} / {{ taskProgress[t.id]?.total ?? (t.config?.search_keywords?.length ?? 0) }}</div>
                    <div :style="{ width: '80%', height: '4px', background: 'var(--card-2)', borderRadius: '999px', overflow: 'hidden' }">
                      <div :style="{ height: '100%', width: (taskProgress[t.id]?.total ? Math.min(100, Math.round((taskProgress[t.id]!.current / Math.max(1, taskProgress[t.id]!.total)) * 100)) : 0) + '%', background: 'var(--primary-deep)', transition: 'width 0.3s ease' }" />
                    </div>
                  </template>
                  <Pill v-else :tone="statusOf(t).tone">{{ statusOf(t).label }}</Pill>
                </div>
                <div class="flex items-center justify-center gap-1">
                  <button v-if="isRunning(t.id)" type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius: '999px', color: 'var(--red, #d85a48)', cursor: 'pointer' }" title="停止监测" @click.stop="cancelTask(t.id)"><Icon name="x" :size="13" /></button>
                  <button v-else type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius: '999px', color: 'var(--primary-deep)', cursor: 'pointer' }" title="立刻监测" @click.stop="runNowTask(t.id)"><Icon name="play" :size="13" /></button>
                  <button type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius: '999px', color: 'var(--ink-3)' }" title="编辑任务" @click.stop="openEdit(t)"><Icon name="edit" :size="13" /></button>
                  <button type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius: '999px', color: 'var(--ink-3)' }" title="删除任务" @click.stop="removeTask(t.id)"><Icon name="trash" :size="13" /></button>
                </div>
              </div>
            </template>
          </div>
        </section>

        <!-- 右卡：任务详情预览 -->
        <section class="flex min-h-0 flex-col" :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }">
          <div v-if="!previewTask" class="flex flex-1 flex-col items-center justify-center text-center" :style="{ color: 'var(--ink-3)' }">
            <div class="text-[14px] font-medium mb-1">暂无任务</div>
            <div class="text-[11.5px]">点击左上「新增任务」开始监测</div>
          </div>
          <template v-else>
            <div class="mb-3 flex-shrink-0">
              <div class="font-display text-[14px] font-semibold">{{ previewTask.name }}</div>
              <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">任务详情</div>
            </div>
            <div class="flex flex-col gap-3 flex-1 min-h-0 overflow-y-auto">
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">目标品牌</div>
                <div class="text-[13px] font-medium">{{ previewTask.config?.target_brand || '—' }}</div>
              </div>
              <div>
                <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">近 7 天趋势</div>
                <LineChart v-if="hasPreviewTrend" :labels="previewTrendLabels" dual-axis :series="[{ label: '命中关键词数', color: TREND_MATCHED_COLOR, data: previewTrendMatched }, { label: '最优排名', color: TREND_RANK_COLOR, data: previewTrendRank }]" />
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">无历史数据 —— 跑几次「立即执行」后会成线。</div>
              </div>
            </div>
            <div class="pt-4 flex-shrink-0 flex gap-2">
              <button type="button" class="flex-1 text-[12.5px] font-medium" :style="{ padding: '9px 14px', background: 'var(--card-2)', border: '1px solid var(--line)', borderRadius: '8px', color: 'var(--ink-2)', cursor: 'pointer' }" @click="exportPreviewCsv()">导出数据</button>
              <button type="button" class="flex-1 text-[12.5px] font-medium" :style="{ padding: '9px 14px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer' }" @click="openSchedule()">定时监测</button>
            </div>
          </template>
        </section>
      </div>
    </template>

    <!-- ═══ L2: 二级关键词 selectedId!==null ═══ -->
    <template v-else>
      <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">

        <!-- 左卡：关键词列表 -->
        <section class="flex min-h-0 flex-col" :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }">
          <div class="mb-3 flex-shrink-0 flex items-start gap-3">
            <button type="button" class="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center" :style="{ background: 'var(--card-2)', border: '1px solid var(--line)', borderRadius: '999px', color: 'var(--ink-2)', cursor: 'pointer' }" title="返回任务列表" @click="backToList()"><Icon name="arrowLeft" :size="14" /></button>
            <div class="min-w-0 flex-1">
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">知乎搜索 · 关键词列表</div>
              <div class="font-display text-[14px] font-semibold mt-0.5">{{ selectedTask?.name ?? '' }}</div>
            </div>
            <a v-if="selectedTask?.target_url" :href="selectedTask.target_url" target="_blank" class="flex-shrink-0 self-center text-[11.5px] text-[var(--primary-deep)] hover:underline">知乎搜索页 ↗</a>
          </div>

          <!-- 知乎特有状态条 -->
          <div v-if="latestStatus === 'error'" class="mb-2 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--red, #d85a48)' }"><Pill tone="alert">鉴权失败</Pill>检查设置页知乎 Access Secret 或系统时钟。</div>
          <div v-if="latestStatus === 'risk_control'" class="mb-2 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-2)' }"><Pill tone="warn">频率限制</Pill>被知乎频率/配额限制（30001），稍后重试。</div>
          <div v-if="fulltextNoCookie" class="mb-2 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-2)' }"><Pill tone="warn">全文匹配未生效</Pill>已开启全文匹配但未配置知乎 Cookie，请到 Cookie 管理添加。</div>

          <div class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase" :style="{ gridTemplateColumns: '1.6fr .6fr .6fr .6fr', letterSpacing: '1.2px', color: 'var(--ink-3)', borderBottom: '1px solid var(--line)' }">
            <div>关键词</div><div class="text-center">命中数</div><div class="text-center">首位</div><div class="text-center">状态</div>
          </div>
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div v-if="!keywordResults.length" class="py-10 text-center text-[12px]" :style="{ color: 'var(--ink-3)' }">还没有结果，点右下「启动监测」。</div>
            <div v-for="(kw, i) in keywordResults" :key="kw.keyword + '-' + i" class="grid items-center cursor-pointer transition"
              :style="{ gridTemplateColumns: '1.6fr .6fr .6fr .6fr', borderBottom: i < keywordResults.length - 1 ? '1px solid var(--line)' : 'none', padding: '12px 8px', background: selectedKeywordIdx === i ? 'var(--card-2)' : 'transparent' }"
              @click="selectedKeywordIdx = i"
              @mouseenter="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
              @mouseleave="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'transparent'; }">
              <div class="min-w-0"><div class="truncate text-[12.5px] font-medium" :style="{ color: 'var(--ink)' }">{{ kw.keyword }}</div></div>
              <div class="text-center font-display text-[13px] font-bold" :style="{ color: kw.matched_count > 0 ? 'var(--primary-deep)' : 'var(--ink-3)' }">{{ kw.matched_count }}</div>
              <div class="text-center text-[12.5px]" :style="{ color: kw.first_rank > 0 ? 'var(--ink)' : 'var(--ink-3)' }">{{ kw.first_rank > 0 ? '#' + kw.first_rank : '—' }}</div>
              <div class="text-center">
                <Pill v-if="kw.fetch_error" tone="alert">失败</Pill>
                <Pill v-else-if="kw.first_rank > 0" tone="ok">命中</Pill>
                <Pill v-else tone="info">未命中</Pill>
              </div>
            </div>
          </div>
        </section>

        <!-- 右卡：单关键词详情 -->
        <section class="flex min-h-0 flex-col overflow-y-auto" :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)', padding: '22px' }">
          <div class="mb-3 flex-shrink-0">
            <div class="font-display text-[14px] font-semibold">关键词详情</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }"><template v-if="currentKeyword">{{ currentKeyword.keyword }}</template><template v-else>选择左侧关键词查看</template></div>
          </div>

          <div class="mb-4 grid flex-shrink-0 grid-cols-2 gap-3">
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">命中条数</div>
              <div class="font-display text-[20px] font-bold">{{ currentKeyword ? currentKeyword.matched_count : 0 }}</div>
            </div>
            <div class="rounded-lg" :style="{ background: 'var(--card-2)', padding: '14px' }">
              <div class="text-[10.5px] uppercase mb-1" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">首位排名</div>
              <div class="font-display text-[20px] font-bold">{{ currentKeyword && currentKeyword.first_rank > 0 ? '#' + currentKeyword.first_rank : '—' }}</div>
            </div>
          </div>

          <div class="flex-1 min-h-0 overflow-y-auto">
            <div v-if="!currentKeyword" class="text-center text-[12px] py-8" :style="{ color: 'var(--ink-3)' }">点击左侧关键词查看排名详情</div>
            <template v-else>
              <div v-if="currentKeyword.fetch_error" class="text-[11.5px] mb-3 px-3 py-2 rounded" :style="{ background: 'rgba(239,68,68,0.08)', color: '#b91c1c', borderLeft: '3px solid #b91c1c' }">抓取失败：{{ currentKeyword.fetch_error.slice(0, 120) }}</div>
              <div v-else-if="currentKeyword.empty_reason" class="text-[11.5px] mb-3" :style="{ color: 'var(--ink-3)' }">知乎无结果：{{ currentKeyword.empty_reason }}</div>
              <table class="w-full text-[12px]">
                <thead class="text-[var(--ink-3)]"><tr><th class="text-left w-8">#</th><th class="text-left">标题</th><th class="text-left w-16">类型</th><th class="text-left w-20">作者</th><th class="text-right w-14">赞同</th></tr></thead>
                <tbody>
                  <tr v-for="r in currentKeyword.results" :key="r.rank" :style="{ background: r.matches_brand ? 'var(--primary-soft)' : 'transparent' }">
                    <td>{{ r.rank }}</td>
                    <td class="truncate max-w-[320px]">
                      <a :href="r.url" target="_blank" class="hover:underline">{{ r.title }}</a>
                      <span v-if="r.matches_brand" class="ml-1 text-[10px] px-1 rounded font-medium" :style="{ background: 'var(--primary-deep)', color: '#fff' }">命中:{{ r.matched_brand }}({{ r.matched_field }})<template v-if="r.matched_field === 'fulltext'"> · 正文</template></span>
                    </td>
                    <td>{{ r.content_type }}</td>
                    <td class="truncate max-w-[80px]">{{ r.author_name }}</td>
                    <td class="text-right">{{ r.voteup_count }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>

          <div class="mt-5 flex-shrink-0">
            <button type="button" class="w-full font-medium text-[14px]" :disabled="isRunning(selectedId!)" :style="{ padding: '12px 24px', borderRadius: '10px', background: isRunning(selectedId!) ? 'var(--card-2)' : 'var(--primary-deep)', color: isRunning(selectedId!) ? 'var(--ink-3)' : '#fff', cursor: isRunning(selectedId!) ? 'not-allowed' : 'pointer', border: 'none' }" @click="runNowTask(selectedId!)">{{ isRunning(selectedId!) ? '监测中…' : '▶ 启动监测' }}</button>
          </div>
        </section>
      </div>
    </template>

    <AddTaskModal v-model:open="showModal" :default-type="'zhihu_search' as any" :editing-task="editingTask as any" @created="onTaskSaved" @updated="onTaskSaved" />
  </div>
</template>
```

- [ ] **Step 3: 类型检查 + 编译**

Run (from `frontend/`): `npx vue-tsc --noEmit -p tsconfig.app.json`
Expected: 无 error（若报 `LineChart` 的 `dual-axis` / `series` prop 类型，对照原文件该用法本就存在，应通过）。
同时确认 vite 控制台（持久后台 `bccwf7wzz`）无编译报错。

- [ ] **Step 4: 手测 L1（browser-dev）**

http://localhost:5173 → 监测中心 → 知乎搜索。用 playwright 截图核对：
- 默认落地在 **L1**（不再直接进详情）：左「监测任务」表（任务名/变化/状态/操作 + 新增任务）、右「任务详情」预览卡（目标品牌 / 近 7 天趋势 / 导出数据·定时监测）。
- hover/点击任务行 → 右卡预览定位该任务；状态列 Pill 正确（`0603` 有命中应显示「正常」）。
- console 0 error。

- [ ] **Step 5: 手测 L2（browser-dev）**

- 点任务名 `0603` → 进 **L2**：左关键词列表（命中数/首位/状态）+ 右单关键词详情（KPI 命中条数·首位排名 + 结果表）。
- 点不同关键词，右卡结果表切换；命中行高亮、`命中:品牌(...)` 标记，`matched_field==='fulltext'` 显示「· 正文」。
- 若开了全文匹配未配 Cookie：左卡顶部出现「全文匹配未生效」状态条。
- 点返回箭头 → 回 L1。`▶ 启动监测` 跑整任务、跑动中禁用显示「监测中…」。
- console 0 error。

- [ ] **Step 6: 手测边角**

- 删除任务（确认弹窗 → 列表刷新）。
- 导出数据：下载 `{任务名}-知乎命中-YYYY-MM-DD.csv`，列 `关键词,命中条数,首位排名`。
- 定时监测：打开编辑弹窗。
- 空态：无结果任务进 L2 显示「还没有结果」。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/monitor/ZhihuSearchModule.vue
git commit -m "feat(monitor-ui): zhihu_search 两级双卡布局（对齐百度排名）"
```

---

## Self-Review

**Spec coverage：**
- 架构镜像/纯前端 → Task 2 ✓
- L1 任务表 + 预览卡（品牌/7天趋势/导出·定时）→ Task 2 template ✓
- L2 关键词列表（命中数/首位/状态 + no_cookie/鉴权/限频状态条）+ 单关键词详情（KPI + 结果表 + 「·正文」 + 启动监测跑整任务）→ Task 2 template ✓
- 状态算法 → Task 1 ✓
- taskHistories fan-out → `loadAllTaskHistories` ✓
- 导出 CSV / 定时监测 → `exportPreviewCsv` / `openSchedule` ✓
- 不做告警 hero / 批量导入 / 双榜 / 卡位率 / L2 单关键词跑 → 均未引入 ✓

**Type 一致性：** `zhihuSearchTaskStatus` 签名在 Task 1 定义、Task 2 `statusOf` 调用一致；`KeywordResult`/`ResultItem` 字段与 zhihu_search.py metric 一致（`first_rank` -1=无命中、`matched_count`、`results`、`fulltext_status`、`matched_field`）。

**Placeholder 扫描：** 无 TBD/TODO；所有 step 含完整代码或精确命令。

**已知非阻塞项：** `LineChart` 的 `dual-axis`/`series` 用法直接沿用原 `ZhihuSearchModule` 既有调用，prop 契约不变。L2 不重复任务级趋势（spec 已记录的取舍）。
