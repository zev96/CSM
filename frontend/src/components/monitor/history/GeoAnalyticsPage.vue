<script setup lang="ts">
/**
 * 数据中心「AI 卡位」pivot —— GEO 卡位分析页（只读）。
 *
 * 自包含组件（IA 大改时会被整体搬走，所以不依赖父组件 props，自己拉
 * 数据、自己管选中态），结构对齐 ZhihuRankingPage + GeoTaskModule：
 *   - 任务选择器：GET /api/monitor/tasks?type=geo_query，默认第一条。
 *   - 4 KPI 卡（最近一次 result.metric）：GET /api/monitor/results?
 *     task_id=&limit=1 → soc（含 status_band 色带）/ first_rank_rate /
 *     sentiment_score / error_cells。
 *   - 卡位矩阵（平台 × KPI）：读 metric.by_platform（{platform:
 *     {soc, first_rank_rate, sentiment_score, status_band, ...}}），
 *     一行一平台，列 SoC / 首推率 / 情感。
 *   - 信源聚合榜：GET /api/monitor/geo/{id}/citations?days= → CitationRow
 *     表（域名 / 类型 / 引用数 / 关键词），带 7/30/90 天 days 过滤。
 *
 * @navigate({ taskId }) 把行/选中任务下钻回监测中心「AI 卡位」tab（跟
 * 现有 zhihu/baidu pivot 的 emit('navigate') 同套路）。
 *
 * 视觉沿用 ZhihuRankingPage 的设计系统 idiom（KPI 卡 card + line 描边、
 * 表格固定表头 + 滚动 body、pivot 胶囊），不另造一套观感。
 */
import { computed, onMounted, ref, watch } from "vue";

import Pill from "@/components/ui/Pill.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import type { Task, CitationRow } from "@/utils/monitor-types";

type Days = 7 | 30 | 90;

// 运行级 KPI 汇总块（geo_query adapter 写进 monitor_results.metric_json，
// 口径见 csm_core/monitor/geo/metrics.py aggregate）。卡位矩阵读 by_platform，
// 它的每个值就是同一套 _block 输出（soc/first_rank_rate/sentiment_score/
// status_band…，注意 _block 不含 sentiment_dist，只有顶层 aggregate 有）。
interface GeoMetricBlock {
  total?: number;
  mentioned?: number;
  soc?: number;
  status_band?: string;
  first_rank_rate?: number;
  first_rank_rate_mentioned?: number;
  sentiment_score?: number;
}
interface GeoMetric extends GeoMetricBlock {
  error_cells?: number;
  by_platform?: Record<string, GeoMetricBlock>;
}
interface LatestResult {
  checked_at: string;
  status: string;
  rank: number;
  metric: GeoMetric;
}

const emit = defineEmits<{ navigate: [payload: { taskId: number }] }>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();

// ── 状态 ───────────────────────────────────────────────────────────────
const tasks = ref<Task[]>([]);
const selectedTaskId = ref<number | null>(null);
const latest = ref<LatestResult | null>(null);
const board = ref<CitationRow[]>([]);
const days = ref<Days>(30);

const tasksLoading = ref(false);
const kpiLoading = ref(false);
const boardLoading = ref(false);

// ── 派生 ───────────────────────────────────────────────────────────────
const selectedTask = computed<Task | null>(
  () => tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
);
const metric = computed<GeoMetric | null>(() => latest.value?.metric ?? null);

// 卡位矩阵行 —— by_platform 是 {platform: block}，转成有序数组（按 SoC 降序）。
const platformRows = computed<Array<{ platform: string; block: GeoMetricBlock }>>(
  () => {
    const bp = metric.value?.by_platform;
    if (!bp) return [];
    return Object.entries(bp)
      .map(([platform, block]) => ({ platform, block }))
      .sort((a, b) => (b.block.soc ?? 0) - (a.block.soc ?? 0));
  },
);

// ── 展示辅助（跟 GeoTaskModule 同口径）───────────────────────────────────
const PLATFORM_LABELS: Record<string, string> = {
  tongyi: "通义千问",
  kimi: "Kimi",
};
function platformLabel(p: string): string {
  return PLATFORM_LABELS[p] ?? p;
}

// 百分比展示（soc / first_rank_rate 是 0–1 ratio）。
function pct(v: number | undefined | null): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}
// 情感得分 -1..1 → 一位小数（带 +/- 号）；na/空显示 —。
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
// 情感分文字颜色（正绿 / 负红 / 其余默认）。
function sentimentColor(v: number | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "var(--ink-3)";
  if (v > 0.05) return "var(--green)";
  if (v < -0.05) return "var(--red, #d85a48)";
  return "var(--ink)";
}

// ── 数据加载 ───────────────────────────────────────────────────────────
async function loadTasks(): Promise<void> {
  tasksLoading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: "geo_query" },
    });
    tasks.value = r.data?.tasks ?? [];
  } catch {
    tasks.value = [];
  } finally {
    tasksLoading.value = false;
  }
}

async function loadLatest(taskId: number): Promise<void> {
  kpiLoading.value = true;
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 1 },
    });
    const rows: LatestResult[] = r.data?.results ?? [];
    latest.value = rows[0] ?? null;
  } catch {
    latest.value = null;
  } finally {
    kpiLoading.value = false;
  }
}

async function loadBoard(taskId: number): Promise<void> {
  boardLoading.value = true;
  try {
    const r = await sidecar.client.get(`/api/monitor/geo/${taskId}/citations`, {
      params: { days: days.value },
    });
    board.value = r.data?.leaderboard ?? [];
  } catch {
    board.value = [];
  } finally {
    boardLoading.value = false;
  }
}

// 任务列表变化 → 收敛选中态（默认第一条）。
watch(
  tasks,
  (list) => {
    if (list.length === 0) {
      selectedTaskId.value = null;
      latest.value = null;
      board.value = [];
      return;
    }
    if (
      selectedTaskId.value == null ||
      !list.find((t) => t.id === selectedTaskId.value)
    ) {
      selectedTaskId.value = list[0].id;
    }
  },
  { immediate: false },
);

// 选中任务变化 → 拉它的 KPI + 信源榜。
watch(selectedTaskId, (id) => {
  if (id == null) {
    latest.value = null;
    board.value = [];
    return;
  }
  void loadLatest(id);
  void loadBoard(id);
});

// days 过滤变化 → 只重拉信源榜。
watch(days, () => {
  if (selectedTaskId.value != null) void loadBoard(selectedTaskId.value);
});

onMounted(loadTasks);
</script>

<template>
  <!--
    h-full + min-h-0 + flex-col 让任务选择器 / KPI / 卡位矩阵保持固定，
    「信源榜」块单独 flex-1 内部滚动。父 wrapper（DataCenterView）是
    overflow-hidden，不会再串到整个数据中心页面。
  -->
  <div class="flex h-full min-h-0 flex-col gap-3">
    <!-- 任务选择器 + days 过滤 -->
    <div class="flex flex-shrink-0 flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <span class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">卡位任务</span>
        <select
          v-model="selectedTaskId"
          class="text-[12.5px] font-medium"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: '999px',
            padding: '6px 14px',
            color: 'var(--ink)',
            cursor: 'pointer',
            maxWidth: '260px',
          }"
        >
          <option v-if="!tasks.length" :value="null" disabled>暂无卡位任务</option>
          <option v-for="t in tasks" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
        <button
          v-if="selectedTask"
          type="button"
          class="inline-flex items-center text-[11.5px]"
          :style="{ color: 'var(--primary-deep, #c9521f)', background: 'transparent', cursor: 'pointer' }"
          title="去监测中心运行 / 编辑这个任务"
          @click="emit('navigate', { taskId: selectedTask.id })"
        >
          去监测 →
        </button>
      </div>

      <!-- days 胶囊：近 7 / 30 / 90 天（只影响信源榜）-->
      <div
        class="inline-flex gap-1 rounded-full p-1"
        :style="{ background: 'var(--card)', border: '1px solid var(--line)' }"
      >
        <button
          v-for="d in ([7, 30, 90] as Days[])"
          :key="d"
          type="button"
          class="rounded-full px-3.5 py-1 text-[12px] font-medium"
          :style="{
            background: days === d ? 'var(--dark)' : 'transparent',
            color: days === d ? 'var(--card)' : 'var(--ink-3)',
          }"
          @click="days = d"
        >
          近 {{ d }} 天
        </button>
      </div>
    </div>

    <!-- 空态：没有 geo 任务 -->
    <div
      v-if="!tasksLoading && !tasks.length"
      class="py-12 text-center text-[12.5px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无 AI 卡位任务 · 去监测中心「AI 卡位」新建任务并运行后，这里展示分析。
    </div>

    <template v-else>
      <!-- 4 KPI 卡（最近一次 result.metric）—— 固定，不滚 -->
      <div class="grid flex-shrink-0 grid-cols-2 gap-2.5 md:grid-cols-4">
        <!-- 曝光度 SoC + 色带 -->
        <div
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner)',
            padding: '14px',
          }"
          class="flex flex-col gap-1.5"
        >
          <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">曝光度 SoC</div>
          <div class="flex items-baseline gap-2">
            <span
              class="font-display font-bold"
              :style="{ fontSize: '26px', lineHeight: 1, color: bandColor(metric?.status_band) }"
            >{{ metric ? pct(metric.soc) : "—" }}</span>
            <span
              v-if="metric?.status_band"
              class="text-[11px] font-medium"
              :style="{ color: bandColor(metric.status_band) }"
            >{{ bandLabel(metric.status_band) }}</span>
          </div>
          <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
            提及 <b :style="{ color: 'var(--ink)' }">{{ metric?.mentioned ?? 0 }}</b> /
            {{ metric?.total ?? 0 }} cell
          </div>
        </div>

        <!-- 首推率 -->
        <div
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner)',
            padding: '14px',
          }"
          class="flex flex-col gap-1.5"
        >
          <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">首推率</div>
          <div class="font-display font-bold" :style="{ fontSize: '26px', lineHeight: 1 }">
            {{ metric ? pct(metric.first_rank_rate) : "—" }}
          </div>
          <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">排第 1 的 cell 占比</div>
        </div>

        <!-- 净情感分 -->
        <div
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner)',
            padding: '14px',
          }"
          class="flex flex-col gap-1.5"
        >
          <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">净情感分</div>
          <div
            class="font-display font-bold"
            :style="{ fontSize: '26px', lineHeight: 1, color: sentimentColor(metric?.sentiment_score) }"
          >
            {{ metric ? sentimentText(metric.sentiment_score) : "—" }}
          </div>
          <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">-1 负 · 0 中 · +1 正</div>
        </div>

        <!-- 采集失败 cell（>0 高亮）-->
        <div
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner)',
            padding: '14px',
          }"
          class="flex flex-col gap-1.5"
        >
          <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">采集失败</div>
          <div class="font-display font-bold" :style="{ fontSize: '26px', lineHeight: 1 }">
            <template v-if="metric">
              <span
                v-if="(metric.error_cells ?? 0) > 0"
                :style="{ color: 'var(--red, #d85a48)' }"
              >{{ metric.error_cells }}</span>
              <span v-else :style="{ color: 'var(--green)', fontSize: '18px' }">全部成功</span>
            </template>
            <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
          </div>
          <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">本次运行失败 cell 数</div>
        </div>
      </div>

      <!-- 还没跑过的提示 -->
      <div
        v-if="!kpiLoading && !latest"
        class="flex-shrink-0 py-3 text-center text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        该任务还没有运行记录 · 去监测中心「AI 卡位」运行一次后显示卡位数据。
      </div>

      <!-- 卡位矩阵（平台 × KPI）—— 固定，不滚 -->
      <div
        v-if="platformRows.length"
        class="flex-shrink-0"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-inner)',
          padding: '14px',
        }"
      >
        <div class="mb-2 text-[12.5px] font-semibold">卡位矩阵 · 各 AI 平台</div>
        <!-- 表头 -->
        <div
          class="grid items-center text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.4fr 1fr 1fr 1fr',
            padding: '6px 10px',
            letterSpacing: '1px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>平台</div>
          <div class="text-center">SoC</div>
          <div class="text-center">首推率</div>
          <div class="text-center">情感</div>
        </div>
        <!-- 行：一平台一行 -->
        <div
          v-for="row in platformRows"
          :key="row.platform"
          class="grid items-center"
          :style="{
            gridTemplateColumns: '1.4fr 1fr 1fr 1fr',
            padding: '10px',
            fontSize: '12.5px',
            borderTop: '1px solid rgba(28,26,23,0.06)',
          }"
        >
          <div class="font-medium" :style="{ color: 'var(--ink)' }">
            {{ platformLabel(row.platform) }}
          </div>
          <div
            class="text-center font-display font-bold"
            :style="{ color: bandColor(row.block.status_band) }"
          >
            {{ pct(row.block.soc) }}
          </div>
          <div class="text-center font-display font-bold">
            {{ pct(row.block.first_rank_rate) }}
          </div>
          <div
            class="text-center font-display font-bold"
            :style="{ color: sentimentColor(row.block.sentiment_score) }"
          >
            {{ sentimentText(row.block.sentiment_score) }}
          </div>
        </div>
      </div>

      <!--
        信源聚合榜 —— 占满剩余高度，header 固定，行列表内部滚动。
        这样信源再多滚动条也只出现在这块卡内，不会污染上面 KPI / 矩阵。
      -->
      <div
        class="flex min-h-0 flex-1 flex-col"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-inner)',
          padding: '12px',
        }"
      >
        <div class="mb-2 flex flex-shrink-0 items-center justify-between">
          <div class="text-[12.5px] font-semibold">信源聚合榜 · 近 {{ days }} 天</div>
          <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">按引用频次降序</div>
        </div>

        <!-- 表头 -->
        <div
          class="grid flex-shrink-0 items-center text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.6fr 80px 70px 2fr',
            padding: '8px 10px',
            letterSpacing: '1px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>域名</div>
          <div>类型</div>
          <div class="text-center">引用</div>
          <div>关键词</div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <div
            v-if="boardLoading"
            class="py-8 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >加载中…</div>
          <div
            v-else-if="!board.length"
            class="py-8 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >暂无信源数据 · 运行后 AI 引用的来源域名会汇总到这里。</div>

          <div
            v-for="row in board"
            v-else
            :key="row.domain"
            class="grid items-center"
            :style="{
              gridTemplateColumns: '1.6fr 80px 70px 2fr',
              padding: '10px',
              fontSize: '12.5px',
              borderTop: '1px solid rgba(28,26,23,0.06)',
            }"
          >
            <div class="truncate font-medium" :style="{ color: 'var(--ink)' }" :title="row.domain">
              {{ row.domain || "—" }}
            </div>
            <div>
              <Pill tone="info">{{ row.source_type }}</Pill>
            </div>
            <div class="text-center font-display text-[13px] font-bold">{{ row.count }}</div>
            <div
              class="truncate"
              :style="{ color: 'var(--ink-3)' }"
              :title="row.keywords.join('、')"
            >
              {{ row.keywords.length ? row.keywords.join("、") : "—" }}
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
