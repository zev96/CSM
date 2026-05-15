<script setup lang="ts">
/**
 * 百度关键词排名页 —— 历史报告 tab 的「百度关键词」子页。
 * 左侧任务列表 + 右侧: 30 天趋势 + 默认搜索结果 + 最新资讯结果。
 */
import { ref, computed, onMounted, watch } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import * as XLSX from "xlsx";
import LineChart from "./LineChart.vue";
import Pill from "@/components/ui/Pill.vue";

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

interface BaiduMetric {
  search_keyword: string;
  target_brands: string[];
  serp_url: string;
  default_results: BaiduResultRow[];
  news_results: BaiduResultRow[];
  default_matched_count: number;
  default_first_rank: number;
  news_first_rank: number;
  news_present: boolean;
  engine: string;
  headless: boolean;
  captcha_hit: boolean;
}

interface TaskItem {
  id: number;
  name: string;
  config: { search_keyword: string; target_brands: string[] };
  last_check_at: string | null;
  last_status: string | null;
}

interface ResultItem {
  task_id: number;
  checked_at: string;
  status: string;
  rank: number;
  metric: BaiduMetric | null;
  error_message: string | null;
}

// ──────────────────────────── store / composables ────────────────────────────

const emit = defineEmits<{
  (e: "add-task"): void;
  (e: "batch-import"): void;
}>();

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

// Trend chart: history is newest-first from API; reverse for chronological
const chronoHistory = computed(() => [...history.value].reverse());

const chartLabels = computed(() =>
  chronoHistory.value.map((r) => r.checked_at.slice(5, 10)),
);

const chartSeries = computed(() => {
  const ranks = chronoHistory.value.map((r) => {
    const v = r.metric?.default_first_rank ?? -1;
    return v > 0 ? v : null;
  });
  const counts = chronoHistory.value.map((r) => r.metric?.default_matched_count ?? 0);
  return [
    { label: "首条排名", color: "#ee6a2a", data: ranks as number[] },
    { label: "自家命中数", color: "#5e7848", data: counts },
  ];
});

// ──────────────────────────── helpers ────────────────────────────

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function taskStatusTone(status: string | null): "ok" | "alert" | "warn" | "info" {
  if (!status) return "info";
  if (status === "ok") return "ok";
  if (status === "captcha" || status === "circuit_break") return "warn";
  if (status === "error" || status === "fail") return "alert";
  return "info";
}

function taskStatusLabel(status: string | null): string {
  if (!status) return "未跑";
  if (status === "ok") return "正常";
  if (status === "captcha") return "验证码";
  if (status === "circuit_break") return "熔断";
  if (status === "error" || status === "fail") return "失败";
  return status;
}

function rowBg(row: BaiduResultRow): string {
  if (row.fetch_error) return "rgba(28,26,23,0.04)";
  if (row.matches_brand) return "rgba(94,120,72,0.08)";
  return "transparent";
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
    if (tasks.value.length > 0 && selectedId.value === null) {
      selectedId.value = tasks.value[0].id;
    }
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
    const r = await sidecar.client.get(`/api/monitor/tasks/${id}/results`, {
      params: { limit: 30 },
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
  try {
    await whenReady();
    await sidecar.client.post(`/api/monitor/tasks/${selectedId.value}/run-now`);
    toast.info("已派发，结果会通过 SSE 流推回");
  } catch (e: any) {
    toast.error(`派发失败: ${e?.message ?? e}`);
  } finally {
    runningNow.value = false;
  }
}

// ──────────────────────────── Excel export ────────────────────────────

function exportExcel() {
  const m = latestMetric.value;
  if (!m) {
    toast.warn("暂无数据可导出");
    return;
  }

  const header = ["排名", "区块", "标题", "链接", "域名", "是否自家", "命中品牌", "抓取来源", "抓取错误"];

  function rowsFromResults(results: BaiduResultRow[], block: string): (string | number | boolean)[][] {
    return results.map((r) => [
      r.rank,
      block,
      r.title,
      r.url,
      r.host,
      r.matches_brand ? "是" : "否",
      r.matched_brand ?? "",
      r.source,
      r.fetch_error ?? "",
    ]);
  }

  const wb = XLSX.utils.book_new();

  // Sheet 1: 默认搜索
  const ws1Data = [header, ...rowsFromResults(m.default_results, "默认搜索")];
  const ws1 = XLSX.utils.aoa_to_sheet(ws1Data);
  XLSX.utils.book_append_sheet(wb, ws1, "默认搜索");

  // Sheet 2: 最新资讯 (only if present)
  if (m.news_present && m.news_results.length > 0) {
    const ws2Data = [header, ...rowsFromResults(m.news_results, "最新资讯")];
    const ws2 = XLSX.utils.aoa_to_sheet(ws2Data);
    XLSX.utils.book_append_sheet(wb, ws2, "最新资讯");
  }

  const keyword = m.search_keyword.replace(/[\\/:*?"<>|]/g, "_");
  XLSX.writeFile(wb, `百度排名_${keyword}.xlsx`);
  toast.success("Excel 已导出");
}

// ──────────────────────────── lifecycle ────────────────────────────

onMounted(loadTasks);

watch(selectedId, (id) => {
  if (id !== null) loadHistory(id);
});
</script>

<template>
  <div class="flex flex-col h-full min-h-0 gap-3" style="padding: 22px;">
    <!-- ── Header: title + 新增任务/批量导入 ── -->
    <div class="flex flex-shrink-0 items-end justify-between gap-3">
      <div class="min-w-0">
        <div class="font-display text-[14px] font-semibold">监测任务</div>
        <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
          百度搜索关键词 · 默认 + 最新资讯 · 自家命中
        </div>
      </div>
      <div class="flex flex-shrink-0 items-center gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1.5"
          :style="{
            height: '32px',
            padding: '0 14px',
            fontSize: '12.5px',
            fontWeight: 500,
            color: 'var(--ink-2)',
            background: 'transparent',
            border: '1px solid var(--line)',
            borderRadius: '999px',
            cursor: 'pointer',
          }"
          @click="emit('batch-import')"
        >
          <span>批量导入</span>
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1.5"
          :style="{
            height: '32px',
            padding: '0 14px',
            fontSize: '12.5px',
            fontWeight: 500,
            color: '#fff',
            background: 'var(--primary-deep)',
            border: 'none',
            borderRadius: '999px',
            cursor: 'pointer',
          }"
          @click="emit('add-task')"
        >
          <span>+ 新增任务</span>
        </button>
      </div>
    </div>

    <div class="flex gap-3 flex-1 min-h-0">
    <!-- ── Left: task list ── -->
    <aside
      class="flex flex-col gap-1 flex-shrink-0 overflow-y-auto"
      :style="{ width: '256px', maxHeight: '100%' }"
    >
      <div
        v-if="loadingTasks"
        class="py-6 text-center text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        加载中…
      </div>
      <div
        v-else-if="tasks.length === 0"
        class="py-6 text-center text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        暂无百度关键词任务
      </div>
      <button
        v-for="task in tasks"
        :key="task.id"
        @click="selectedId = task.id"
        class="flex flex-col gap-1 text-left w-full px-3 py-2.5 rounded-lg"
        :style="{
          background: selectedId === task.id ? 'var(--card-2)' : 'transparent',
          border: selectedId === task.id ? '1px solid var(--line)' : '1px solid transparent',
          cursor: 'pointer',
        }"
      >
        <div class="text-[12.5px] font-medium" :style="{ color: 'var(--ink)' }">
          {{ task.name }}
        </div>
        <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
          {{ task.config.search_keyword }}
        </div>
        <div class="flex items-center gap-1.5 mt-0.5">
          <Pill :tone="taskStatusTone(task.last_status)">
            {{ taskStatusLabel(task.last_status) }}
          </Pill>
          <span class="text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
            {{ fmtDateTime(task.last_check_at) }}
          </span>
        </div>
      </button>
    </aside>

    <!-- ── Right: detail ── -->
    <main class="flex-1 flex flex-col gap-3 min-w-0 overflow-y-auto">
      <!-- empty state -->
      <div
        v-if="!selectedTask"
        class="py-16 text-center text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        请在左侧选择任务
      </div>

      <template v-else>
        <!-- Header -->
        <div class="flex items-start justify-between gap-3 flex-shrink-0">
          <div>
            <div class="font-display text-[14px] font-semibold">{{ selectedTask.name }}</div>
            <div class="text-[11px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
              关键词:
              <b :style="{ color: 'var(--ink)' }">{{ selectedTask.config.search_keyword }}</b>
              <span v-if="latestMetric?.serp_url" class="ml-2">
                ·
                <a
                  :href="latestMetric.serp_url"
                  target="_blank"
                  rel="noopener"
                  class="underline"
                  :style="{ color: 'var(--ink-3)' }"
                >SERP 链接</a>
              </span>
            </div>
          </div>
          <div class="flex gap-2 flex-shrink-0">
            <button
              @click="runNow"
              :disabled="runningNow"
              class="px-3.5 py-1.5 rounded-lg text-[12px] font-medium"
              :style="{
                background: 'var(--dark)',
                color: 'var(--card)',
                opacity: runningNow ? 0.6 : 1,
                cursor: runningNow ? 'not-allowed' : 'pointer',
              }"
            >
              {{ runningNow ? "派发中…" : "立即执行" }}
            </button>
            <button
              @click="exportExcel"
              class="px-3.5 py-1.5 rounded-lg text-[12px] font-medium"
              :style="{
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
                cursor: 'pointer',
              }"
            >
              导出 Excel
            </button>
          </div>
        </div>

        <!-- Status badges -->
        <div class="flex items-center gap-2 flex-wrap flex-shrink-0">
          <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
            上次检查: <b :style="{ color: 'var(--ink)' }">{{ fmtDateTime(latestResult?.checked_at ?? null) }}</b>
          </span>
          <template v-if="latestMetric">
            <Pill tone="info">{{ latestMetric.headless ? "有头模式" : "无头模式" }}</Pill>
            <Pill v-if="latestMetric.captcha_hit" tone="warn">遭遇验证码</Pill>
            <Pill v-else tone="ok">无验证码</Pill>
            <Pill tone="info">{{ latestMetric.engine }}</Pill>
            <Pill v-if="latestMetric.news_present" tone="info">有最新资讯</Pill>
          </template>
          <div
            v-if="loadingHistory"
            class="text-[11px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            加载中…
          </div>
        </div>

        <!-- Trend chart -->
        <div
          v-if="chronoHistory.length > 1"
          :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
        >
          <div class="flex justify-between items-center mb-2">
            <div class="text-[12.5px] font-semibold">近 30 天趋势</div>
            <div class="flex gap-3 text-[11px]" :style="{ color: 'var(--ink-2)' }">
              <span>
                <span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#ee6a2a', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />
                首条排名
              </span>
              <span>
                <span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#5e7848', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />
                自家命中数
              </span>
            </div>
          </div>
          <LineChart :labels="chartLabels" :series="chartSeries" />
        </div>

        <!-- No data state -->
        <div
          v-if="!loadingHistory && !latestMetric"
          class="py-10 text-center text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          暂无检查记录
        </div>

        <!-- 默认搜索结果 -->
        <div
          v-if="latestMetric"
          :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
        >
          <div class="flex items-center justify-between mb-3">
            <div class="text-[12.5px] font-semibold">
              当前结果 · 默认搜索
              <span class="font-normal text-[11px] ml-1" :style="{ color: 'var(--ink-3)' }">
                ({{ latestMetric.default_results.length }} 条)
              </span>
            </div>
            <div class="flex gap-2 text-[11px]">
              <span>
                命中 <b :style="{ color: '#5e7848' }">{{ latestMetric.default_matched_count }}</b>
              </span>
              <span v-if="latestMetric.default_first_rank > 0">
                · 首位 <b :style="{ color: '#ee6a2a' }">#{{ latestMetric.default_first_rank }}</b>
              </span>
            </div>
          </div>

          <!-- Table header -->
          <div
            class="grid text-[10.5px] font-medium"
            :style="{
              gridTemplateColumns: '36px 1fr 140px 80px 80px',
              padding: '0 8px 6px',
              color: 'var(--ink-3)',
              borderBottom: '1px solid var(--line)',
            }"
          >
            <div>排名</div>
            <div>标题</div>
            <div>域名</div>
            <div>自家?</div>
            <div>来源</div>
          </div>

          <!-- Table rows -->
          <div
            v-for="row in latestMetric.default_results"
            :key="row.rank"
            :style="{ background: rowBg(row) }"
            class="rounded-lg mt-0.5"
          >
            <div
              class="grid items-center gap-1.5 text-[11.5px]"
              :style="{
                gridTemplateColumns: '36px 1fr 140px 80px 80px',
                padding: '8px',
              }"
            >
              <div class="font-semibold text-center" :style="{ color: 'var(--ink-2)' }">#{{ row.rank }}</div>
              <div class="min-w-0">
                <a
                  :href="row.url"
                  target="_blank"
                  rel="noopener"
                  class="underline truncate block"
                  :style="{ color: 'var(--ink)', maxWidth: '100%' }"
                >{{ row.title }}</a>
              </div>
              <div class="truncate text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ row.host }}</div>
              <div>
                <Pill v-if="row.matches_brand" tone="ok">命中: {{ row.matched_brand }}</Pill>
                <Pill v-else-if="row.fetch_error" tone="alert">抓取失败</Pill>
                <Pill v-else tone="info">{{ row.host }}</Pill>
              </div>
              <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">{{ row.source }}</div>
            </div>
            <details
              v-if="row.content_preview"
              class="px-8 pb-2"
              :style="{ fontSize: '11px', color: 'var(--ink-3)' }"
            >
              <summary :style="{ cursor: 'pointer', userSelect: 'none' }">摘要</summary>
              <p class="mt-1 leading-relaxed">{{ row.content_preview }}</p>
            </details>
          </div>

          <div
            v-if="latestMetric.default_results.length === 0"
            class="py-4 text-center text-[11.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            无结果
          </div>
        </div>

        <!-- 最新资讯结果 -->
        <div
          v-if="latestMetric?.news_present"
          :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
        >
          <div class="flex items-center justify-between mb-3">
            <div class="text-[12.5px] font-semibold">
              当前结果 · 最新资讯
              <span class="font-normal text-[11px] ml-1" :style="{ color: 'var(--ink-3)' }">
                ({{ latestMetric.news_results.length }} 条)
              </span>
            </div>
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
              <span v-if="latestMetric.news_first_rank > 0">
                首位 <b :style="{ color: '#ee6a2a' }">#{{ latestMetric.news_first_rank }}</b>
              </span>
              <span v-else>未命中</span>
            </div>
          </div>

          <!-- Table header -->
          <div
            class="grid text-[10.5px] font-medium"
            :style="{
              gridTemplateColumns: '36px 1fr 140px 80px 80px',
              padding: '0 8px 6px',
              color: 'var(--ink-3)',
              borderBottom: '1px solid var(--line)',
            }"
          >
            <div>排名</div>
            <div>标题</div>
            <div>域名</div>
            <div>自家?</div>
            <div>来源</div>
          </div>

          <!-- Table rows (max 3 shown by plan) -->
          <div
            v-for="row in latestMetric.news_results.slice(0, 3)"
            :key="row.rank"
            :style="{ background: rowBg(row) }"
            class="rounded-lg mt-0.5"
          >
            <div
              class="grid items-center gap-1.5 text-[11.5px]"
              :style="{
                gridTemplateColumns: '36px 1fr 140px 80px 80px',
                padding: '8px',
              }"
            >
              <div class="font-semibold text-center" :style="{ color: 'var(--ink-2)' }">#{{ row.rank }}</div>
              <div class="min-w-0">
                <a
                  :href="row.url"
                  target="_blank"
                  rel="noopener"
                  class="underline truncate block"
                  :style="{ color: 'var(--ink)', maxWidth: '100%' }"
                >{{ row.title }}</a>
              </div>
              <div class="truncate text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ row.host }}</div>
              <div>
                <Pill v-if="row.matches_brand" tone="ok">命中: {{ row.matched_brand }}</Pill>
                <Pill v-else-if="row.fetch_error" tone="alert">抓取失败</Pill>
                <Pill v-else tone="info">{{ row.host }}</Pill>
              </div>
              <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">{{ row.source }}</div>
            </div>
            <details
              v-if="row.content_preview"
              class="px-8 pb-2"
              :style="{ fontSize: '11px', color: 'var(--ink-3)' }"
            >
              <summary :style="{ cursor: 'pointer', userSelect: 'none' }">摘要</summary>
              <p class="mt-1 leading-relaxed">{{ row.content_preview }}</p>
            </details>
          </div>

          <div
            v-if="latestMetric.news_results.length === 0"
            class="py-4 text-center text-[11.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            无资讯结果
          </div>
        </div>
      </template>
    </main>
    </div>
  </div>
</template>
