<script setup lang="ts">
/**
 * 知乎搜索排名监控模块 —— 拉 zhihu_search 任务、跑、展示最新结果的前 10
 * 命中情况。数据形状对齐 csm_core/monitor/platforms/zhihu_search.py 的 metric。
 */
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { subscribe } from "@/api/client";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import Pill from "@/components/ui/Pill.vue";
import LineChart from "./history/LineChart.vue";
import AddTaskModal from "./AddTaskModal.vue";

interface ResultItem {
  rank: number;
  title: string;
  content_type: string;
  url: string;
  voteup_count: number;
  author_name: string;
  matches_brand: boolean;
  matched_brand: string | null;
  matched_field: string | null;
  excerpt: string;
}
interface KeywordResult {
  keyword: string;
  results: ResultItem[];
  matched_count: number;
  first_rank: number;
  result_count: number;
  empty_reason: string | null;
  api_code: number | null;
  fetch_error: string | null;
}
interface Task {
  id: number;
  type: string;
  name: string;
  target_url: string;
  enabled: boolean;
  schedule_cron: string;
  last_check_at: string | null;
  last_status: string | null;
  config?: Record<string, any>;
}

const sidecar = useSidecar();
const monitorStatus = useMonitorStatus();
const toast = useToast();

const tasks = ref<Task[]>([]);
const selectedId = ref<number | null>(null);
const latestMetric = ref<Record<string, any> | null>(null);
const latestStatus = ref<string | null>(null);
// 任务列表加载失败标记 —— SSE 回调 / onMounted 拉表撞 sidecar 503/重启时
// 置 true，模板上给一个「加载失败」可重试入口（对齐 GeoTaskModule.failed）。
const loadFailed = ref(false);
const showModal = ref(false);
const editingTask = ref<Task | null>(null);

const selected = computed(() => tasks.value.find((t) => t.id === selectedId.value) || null);
const keywordResults = computed<KeywordResult[]>(() => latestMetric.value?.keywords ?? []);

// ── 近 7 天趋势 ───────────────────────────────────────────────────────────
// result 历史（desc，最新在前），喂趋势图。复用 loadLatest 一次拉够，避免再发一次。
const taskResults = ref<any[]>([]);
// 知乎搜索固定取前 10（count=10），排名哨兵 = 11 表示「掉出前 10」。
const RANK_SENTINEL = 11;
// 7 天日历 scaffold（今天 → 6 天前），对齐 ZhihuMonitorModule.sparkBuckets：
// 同一天多次跑取最新一次；没数据的天 = null（LineChart spanGaps=false 自动画 gap，
// 语义是「那天没监测」，区别于「那天命中 0 条」）。
const trendBuckets = computed<Array<{ iso: string; label: string; matched: number | null; rank: number | null }>>(() => {
  const out: Array<{ iso: string; label: string; matched: number | null; rank: number | null }> = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ iso, label: String(d.getDate()), matched: null, rank: null });
  }
  const placed = new Set<string>();
  for (const r of taskResults.value) {
    const d = new Date(r.checked_at);
    if (Number.isNaN(d.getTime())) continue;
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (placed.has(iso)) continue; // 同日只放最新一次（taskResults 已 desc）
    const bucket = out.find((b) => b.iso === iso);
    if (bucket) {
      bucket.matched = Number(r.metric?.matched_keywords ?? 0);
      const rk = Number(r.rank ?? -1);
      // best_first_rank：>0 直接用；-1（前 10 无命中）映射成哨兵，曲线落到「前 10 之外」。
      bucket.rank = rk > 0 ? rk : RANK_SENTINEL;
      placed.add(iso);
    }
  }
  return out;
});
const trendLabels = computed<string[]>(() => trendBuckets.value.map((b) => b.label));
const trendMatched = computed<(number | null)[]>(() => trendBuckets.value.map((b) => b.matched));
const trendRank = computed<(number | null)[]>(() => trendBuckets.value.map((b) => b.rank));
// 至少一个 bucket 有数据才画图（否则提示「跑几次后出趋势」）。
const hasTrendData = computed(() => trendBuckets.value.some((b) => b.matched !== null));
// chart.js 走 canvas，strokeStyle 不解析 CSS var()，故传具体 hex（取自主题色 fallback）。
const TREND_MATCHED_COLOR = "#c9521f"; // primary-deep
const TREND_RANK_COLOR = "#8a8580"; // 中性灰

async function loadTasks() {
  // GET /api/monitor/tasks → { count, tasks: [...] }（已核对 routes/monitor.py:41-48）
  // try/catch 对齐 GeoTaskModule.loadTasks：从 SSE finished/failed 回调 + onMounted
  // 调起，sidecar 503/重启时不能让 unhandled rejection 静默吞掉 —— 置 loadFailed
  // 让模板出「加载失败」可重试入口；503（sidecar 还没起来）不弹 toast 免打扰。
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: "zhihu_search" } });
    tasks.value = r.data.tasks ?? [];
    loadFailed.value = false;
    if (selectedId.value === null && tasks.value.length) {
      selectTask(tasks.value[0].id);
    }
  } catch (e: any) {
    loadFailed.value = true;
    if (e?.response?.status !== 503) {
      toast.error(`加载失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    }
  }
}

async function loadLatest(taskId: number) {
  // GET /api/monitor/results → { task_id, count, results: [...] }，行含 .metric / .status
  // （已核对 routes/monitor.py:175-183 + services/monitor_service.py:result_to_dict）
  // 静默兜底：拿不到 latest 不弹 toast（详情区已有「还没有结果」空态），只防
  // unhandled rejection；对齐 GeoTaskModule.loadLatest。
  try {
    // limit 30：一次拉够喂趋势图（trendBuckets 只看近 7 天，多拉无妨且省一次请求）。
    const r = await sidecar.client.get("/api/monitor/results", { params: { task_id: taskId, limit: 30 } });
    const rows = r.data.results ?? [];
    taskResults.value = rows;
    if (rows.length) {
      latestMetric.value = rows[0].metric ?? null;
      latestStatus.value = rows[0].status ?? null;
    } else {
      latestMetric.value = null;
      latestStatus.value = null;
    }
  } catch {
    taskResults.value = [];
    latestMetric.value = null;
    latestStatus.value = null;
  }
}

async function selectTask(id: number) {
  selectedId.value = id;
  await loadLatest(id);
}

async function runNow(id: number) {
  // run-state 走共享 useMonitorStatus store（不再用本地 Set）：乐观 markRunning，
  // POST 失败回滚 clearRunning，成功后由 SSE finished/failed 清。这样切 tab /
  // 重挂载丢了 SSE 事件时，store 的 hydrate() + 30s 轮询仍能恢复在跑状态，
  // 「立即执行」按钮不会永远卡「运行中…」。对齐 GeoTaskModule.runNow。
  monitorStatus.markRunning(id);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${id}/run-now`, {});
  } catch (e: any) {
    monitorStatus.clearRunning(id);
    toast.error(`触发失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

async function removeTask(id: number) {
  // 不要用浏览器原生 confirm()：Tauri 2 WebView2 会把 window.confirm 路由到已
  // 退役的 dialog|confirm IPC 命令 → 抛「Command not found」→ 删除静默 no-op。
  // 用项目通用 confirmDialog（纯 Vue 模态，无 Tauri 依赖），对齐 GeoTaskModule /
  // BaiduRankingPage。
  if (
    !(await confirmDialog("确认删除这个知乎搜索监控任务？", {
      title: "删除监测任务",
    }))
  )
    return;
  try {
    await sidecar.client.delete(`/api/monitor/tasks/${id}`);
    toast.success("已删除");
    if (selectedId.value === id) { selectedId.value = null; latestMetric.value = null; }
    await loadTasks();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

function openAdd() { editingTask.value = null; showModal.value = true; }
function openEdit(t: Task) { editingTask.value = t; showModal.value = true; }

async function onTaskSaved() {
  showModal.value = false;
  await loadTasks();
  if (selectedId.value !== null) await loadLatest(selectedId.value);
}

let stopSSE: (() => void) | null = null;
onMounted(async () => {
  await loadTasks();
  // 从 /api/monitor/running 同步在跑任务（重挂载恢复 in-flight 状态），
  // 对齐 GeoTaskModule。store 自身也每 30s 轮询兜底。
  void monitorStatus.hydrate();
  stopSSE = subscribe("/api/monitor/events", {
    finished: async (d: any) => {
      if (typeof d?.task_id === "number") monitorStatus.clearRunning(d.task_id);
      await loadTasks();
      const sel = selectedId.value;
      if (sel !== null && d?.task_id === sel) await loadLatest(sel);
    },
    failed: async (d: any) => {
      if (typeof d?.task_id === "number") monitorStatus.clearRunning(d.task_id);
      await loadTasks();
    },
  });
});
onUnmounted(() => { if (stopSSE) stopSSE(); });
</script>

<template>
  <div class="flex gap-4">
    <!-- 左：任务列表 -->
    <div class="w-[240px] shrink-0 flex flex-col gap-2">
      <button type="button" class="text-[12.5px] px-3 py-2 rounded bg-[var(--ink)] text-white" @click="openAdd">
        + 新增知乎搜索监控
      </button>
      <!-- 加载失败可重试入口（sidecar 503/重启时 loadTasks 置 loadFailed）。 -->
      <div
        v-if="loadFailed"
        class="text-[12px] px-3 py-2 rounded border"
        :style="{ color: 'var(--red, #d85a48)', borderColor: 'var(--red, #d85a48)' }"
      >
        任务列表加载失败。
        <button type="button" class="underline" @click="loadTasks()">重试</button>
      </div>
      <div
        v-for="t in tasks" :key="t.id"
        class="px-3 py-2 rounded cursor-pointer text-[12.5px] border"
        :style="{
          background: t.id === selectedId ? 'var(--card-2)' : 'transparent',
          borderColor: 'var(--line)',
        }"
        @click="selectTask(t.id)"
      >
        <div class="font-medium truncate">{{ t.name }}</div>
        <div class="text-[11px] text-[var(--ink-3)]">
          {{ t.last_status ?? "未运行" }} · {{ t.schedule_cron }}
        </div>
      </div>
      <div v-if="!tasks.length && !loadFailed" class="text-[12px] text-[var(--ink-3)] px-1">
        还没有知乎搜索监控任务。
      </div>
    </div>

    <!-- 右：详情 -->
    <div class="flex-1 min-w-0">
      <div v-if="!selected" class="text-[13px] text-[var(--ink-3)] p-6">
        从左侧选择或新建一个任务。
      </div>
      <div v-else class="flex flex-col gap-3">
        <div class="flex items-center gap-2">
          <div class="text-[14px] font-medium">{{ selected.name }}</div>
          <a :href="selected.target_url" target="_blank" class="text-[11.5px] text-[var(--primary-deep)] hover:underline">知乎搜索页 ↗</a>
          <div class="ml-auto flex gap-2">
            <button type="button" class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" :disabled="monitorStatus.isRunning(selected.id)" @click="runNow(selected.id)">
              {{ monitorStatus.isRunning(selected.id) ? "运行中…" : "立即执行" }}
            </button>
            <button type="button" class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" @click="openEdit(selected)">编辑</button>
            <button type="button" class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" @click="removeTask(selected.id)">删除</button>
          </div>
        </div>

        <div v-if="latestStatus === 'error'" class="flex items-center gap-2 text-[12px]" :style="{ color: 'var(--red, #d85a48)' }">
          <Pill tone="alert">鉴权失败</Pill>
          检查设置页的知乎 Access Secret，或系统时钟是否准确。
        </div>
        <div v-if="latestStatus === 'risk_control'" class="flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-2)' }">
          <Pill tone="warn">频率限制</Pill>
          被知乎频率/配额限制（30001），稍后重试。
        </div>
        <div v-if="!latestMetric" class="text-[12px] text-[var(--ink-3)]">还没有结果，点「立即执行」。</div>

        <!-- 趋势卡：近 7 天 命中关键词数（左轴）+ 最优排名（右轴，越低越靠前） -->
        <div v-if="latestMetric" class="border rounded p-3" :style="{ borderColor: 'var(--line)' }">
          <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2 text-[12px]">
            <span class="font-medium">近 7 天趋势</span>
            <span class="flex items-center gap-1 text-[var(--ink-2)]">
              <i class="inline-block w-2.5 h-2.5 rounded-sm" :style="{ background: TREND_MATCHED_COLOR }"></i>命中关键词数
            </span>
            <span class="flex items-center gap-1 text-[var(--ink-2)]">
              <i class="inline-block w-2.5 h-2.5 rounded-sm" :style="{ background: TREND_RANK_COLOR }"></i>最优排名（越低越靠前，11=掉出前10）
            </span>
          </div>
          <LineChart
            v-if="hasTrendData"
            :labels="trendLabels"
            dual-axis
            :series="[
              { label: '命中关键词数', color: TREND_MATCHED_COLOR, data: trendMatched },
              { label: '最优排名', color: TREND_RANK_COLOR, data: trendRank },
            ]"
          />
          <div v-else class="text-[12px] text-[var(--ink-3)] py-6 text-center">
            还没有足够的历史数据 —— 跑几次（或等定时任务积累几天）后这里出趋势。
          </div>
        </div>

        <!-- 每个关键词一张卡 -->
        <div v-for="kw in keywordResults" :key="kw.keyword" class="border rounded p-3" :style="{ borderColor: 'var(--line)' }">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[13px] font-medium">{{ kw.keyword }}</span>
            <Pill v-if="kw.first_rank > 0" tone="ok">
              首位命中 #{{ kw.first_rank }} · 共 {{ kw.matched_count }} 条
            </Pill>
            <Pill v-else tone="info">前 10 无命中</Pill>
            <span v-if="kw.fetch_error" class="text-[11px]" :style="{ color: 'var(--red, #d85a48)' }">{{ kw.fetch_error }}</span>
            <span v-else-if="kw.empty_reason" class="text-[11px] text-[var(--ink-3)]">知乎无结果：{{ kw.empty_reason }}</span>
          </div>
          <table class="w-full text-[12px]">
            <thead class="text-[var(--ink-3)]">
              <tr><th class="text-left w-8">#</th><th class="text-left">标题</th><th class="text-left w-16">类型</th><th class="text-left w-20">作者</th><th class="text-right w-14">赞同</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="r in kw.results" :key="r.rank"
                :style="{ background: r.matches_brand ? 'var(--primary-soft)' : 'transparent' }"
              >
                <td>{{ r.rank }}</td>
                <td class="truncate max-w-[320px]">
                  <a :href="r.url" target="_blank" class="hover:underline">{{ r.title }}</a>
                  <span
                    v-if="r.matches_brand"
                    class="ml-1 text-[10px] px-1 rounded font-medium"
                    :style="{ background: 'var(--primary-deep)', color: '#fff' }"
                  >命中:{{ r.matched_brand }}({{ r.matched_field }})</span>
                </td>
                <td>{{ r.content_type }}</td>
                <td class="truncate max-w-[80px]">{{ r.author_name }}</td>
                <td class="text-right">{{ r.voteup_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <AddTaskModal
      v-model:open="showModal"
      :default-type="'zhihu_search' as any"
      :editing-task="editingTask as any"
      @created="onTaskSaved"
      @updated="onTaskSaved"
    />
  </div>
</template>
