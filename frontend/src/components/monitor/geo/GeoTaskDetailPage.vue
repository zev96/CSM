<script setup lang="ts">
/**
 * GEO「卡位仪表盘」L2 详情页 —— 在 GeoTaskModule 的任务列表里点任务名钻入，
 * 一个全宽页面（L1 列表隐藏、本页显示，返回按钮还原列表，跟
 * ZhihuMonitorModule 的批次 L1→L2 同手势）。
 *
 * 自包含（IA 大改会整体搬走）：自己拉
 *   - 最近一次 result.metric（GET /api/monitor/results?task_id=&limit=1）→ 4 KPI
 *   - 最近一跑的全部 cell（GET /api/monitor/geo/{id}/latest-cells）→ 卡位矩阵
 *     （关键词 × 平台）；每个 populated cell 可点开下钻抽屉看
 *     AI 原文 / 推荐顺序（高亮 is_target=你的品牌）/ 情感 / 状态 / 引用信源。
 *   - 信源聚合榜（GET /api/monitor/geo/{id}/citations?days=&platform=）带平台过滤。
 *
 * 运行 / 编辑 / 删除 / 停止 不在本页直接调接口，emit 给父组件复用其既有
 * 处理（单一 toast + confirm + monitorStatus 乐观标记），跨页状态一致。
 *
 * 视觉沿用 GeoTaskModule / ZhihuMonitorModule 的设计系统 idiom（card +
 * Pill + 表格 + var(--*) 色），不另造观感。
 */
import { computed, onMounted, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";

import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { GEO_PLATFORMS } from "@/utils/monitor-types";
import type { Task, CitationRow } from "@/utils/monitor-types";

const props = defineProps<{ task: Task }>();
const emit = defineEmits<{
  (e: "back"): void;
  (e: "run", taskId: number): void;
  (e: "cancel", taskId: number): void;
  (e: "edit", task: Task): void;
  (e: "delete", taskId: number): void;
}>();

const sidecar = useSidecar();
const monitorStatus = useMonitorStatus();

// ── 类型（与后端 metric / cell 形状对齐）─────────────────────────────────
interface GeoMetric {
  soc?: number;
  status_band?: string;
  first_rank_rate?: number;
  sentiment_score?: number;
  error_cells?: number;
  total?: number;
  ok_total?: number;
  mentioned?: number;
}
interface LatestResult {
  checked_at: string;
  status: string;
  rank: number;
  metric: GeoMetric;
}
interface RecommendedEntity {
  name: string;
  position: number;
  is_target: boolean;
}
interface CellCitation {
  url: string;
  title: string;
  domain: string;
  source_type: string;
}
// /api/monitor/geo/{id}/latest-cells 的 cells[] 元素（geo_storage 水合后）。
interface GeoCellRow {
  platform: string;
  keyword: string;
  mentioned: boolean | number;
  rank: number;
  sentiment: string;
  status: string;
  answer_text: string;
  citations: CellCitation[];
  recommended: RecommendedEntity[];
  summary: string;
}

// ── 状态 ───────────────────────────────────────────────────────────────
const latest = ref<LatestResult | null>(null);
const cells = ref<GeoCellRow[]>([]);
const cellsLoading = ref(false);

const board = ref<CitationRow[]>([]);
const boardLoading = ref(false);
// 信源榜平台过滤（'' = 全部）。
const boardPlatform = ref<string>("");

// 下钻抽屉
const drillCell = ref<GeoCellRow | null>(null);

// ── 平台 / 配置派生 ──────────────────────────────────────────────────────
const PLATFORM_LABEL: Record<string, string> = Object.fromEntries(
  GEO_PLATFORMS.map((p) => [p.value, p.label]),
);
function platformLabel(value: string): string {
  return PLATFORM_LABEL[value] ?? value;
}

const cfg = computed<Record<string, any>>(() => props.task.config ?? {});
const brand = computed<string>(() => String(cfg.value.brand ?? props.task.name ?? ""));
const aliases = computed<string[]>(() =>
  Array.isArray(cfg.value.brand_aliases) ? cfg.value.brand_aliases.filter(Boolean) : [],
);
const configKeywords = computed<string[]>(() =>
  Array.isArray(cfg.value.keywords) ? cfg.value.keywords.filter(Boolean) : [],
);
const configPlatforms = computed<string[]>(() =>
  Array.isArray(cfg.value.platforms) ? cfg.value.platforms.filter(Boolean) : [],
);
const webSearch = computed<boolean>(() => cfg.value.web_search !== false);

// ── 卡位矩阵：从 cells 派生行（关键词）与列（平台）───────────────────────
// 平台列优先用 config.platforms（保证空跑也成列），并补上 cells 里出现但
// config 没有的平台；关键词行优先 config.keywords，同样补 cells 里出现的。
const matrixPlatforms = computed<string[]>(() => {
  const seen = new Set<string>(configPlatforms.value);
  for (const c of cells.value) seen.add(c.platform);
  return Array.from(seen);
});
const matrixKeywords = computed<string[]>(() => {
  const seen = new Set<string>(configKeywords.value);
  for (const c of cells.value) seen.add(c.keyword);
  return Array.from(seen);
});

// (keyword, platform) → cell 快速查表。
const cellIndex = computed<Map<string, GeoCellRow>>(() => {
  const m = new Map<string, GeoCellRow>();
  for (const c of cells.value) m.set(`${c.keyword} ${c.platform}`, c);
  return m;
});
function cellAt(keyword: string, platform: string): GeoCellRow | null {
  return cellIndex.value.get(`${keyword} ${platform}`) ?? null;
}

function isMentioned(c: GeoCellRow): boolean {
  return c.mentioned === true || c.mentioned === 1;
}
function isFailed(c: GeoCellRow): boolean {
  return c.status === "error" || c.status === "blocked";
}

// ── 展示工具 ─────────────────────────────────────────────────────────────
function pct(v: number | undefined | null): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}
function sentimentText(v: number | undefined | null): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}
function bandColor(band: string | undefined): string {
  if (band === "strong") return "var(--green)";
  if (band === "weak") return "var(--primary-deep, #c9521f)";
  return "var(--red, #d85a48)";
}
function bandLabel(band: string | undefined): string {
  if (band === "strong") return "强曝光";
  if (band === "weak") return "弱曝光";
  if (band === "hidden") return "未露出";
  return "—";
}
// cell 情感 → 颜色点（pos 绿 / neu 灰 / neg 红 / na 透明）。
function sentimentDot(sentiment: string): string {
  if (sentiment === "pos") return "var(--green)";
  if (sentiment === "neg") return "var(--red, #d85a48)";
  if (sentiment === "neu") return "var(--ink-3)";
  return "transparent";
}
function sentimentLabel(sentiment: string): string {
  if (sentiment === "pos") return "正面";
  if (sentiment === "neg") return "负面";
  if (sentiment === "neu") return "中性";
  return "未判定";
}
function statusLabel(status: string): string {
  if (status === "ok") return "正常";
  if (status === "blocked") return "被拦截";
  if (status === "error") return "采集失败";
  if (status === "empty") return "空回答";
  return status;
}

// 上次运行时间（最近一次 result.checked_at），本地化简写。
const lastRunText = computed<string>(() => {
  const iso = latest.value?.checked_at ?? props.task.last_check_at;
  if (!iso) return "尚未运行";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "尚未运行";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
});

// 运行中状态（store 全局 SSE）。
function progressRatio(): number | null {
  const p = monitorStatus.progressOf(props.task.id);
  if (!p || p.total <= 0) return null;
  return p.current / p.total;
}
const running = computed<boolean>(() => monitorStatus.isRunning(props.task.id));

// ── 数据加载 ───────────────────────────────────────────────────────────
async function loadLatest(): Promise<void> {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: props.task.id, limit: 1 },
    });
    const rows: any[] = r.data?.results ?? [];
    latest.value = rows[0] ?? null;
  } catch {
    latest.value = null;
  }
}

async function loadCells(): Promise<void> {
  cellsLoading.value = true;
  try {
    const r = await sidecar.client.get(`/api/monitor/geo/${props.task.id}/latest-cells`);
    cells.value = (r.data?.cells ?? []) as GeoCellRow[];
  } catch {
    cells.value = [];
  } finally {
    cellsLoading.value = false;
  }
}

async function loadBoard(): Promise<void> {
  boardLoading.value = true;
  try {
    const params: Record<string, any> = { days: 30 };
    if (boardPlatform.value) params.platform = boardPlatform.value;
    const r = await sidecar.client.get(`/api/monitor/geo/${props.task.id}/citations`, {
      params,
    });
    board.value = r.data?.leaderboard ?? [];
  } catch {
    board.value = [];
  } finally {
    boardLoading.value = false;
  }
}

async function reloadAll(): Promise<void> {
  await Promise.all([loadLatest(), loadCells(), loadBoard()]);
}

function openDrill(c: GeoCellRow | null): void {
  if (!c) return;
  drillCell.value = c;
}
function closeDrill(): void {
  drillCell.value = null;
}

// 信源榜平台过滤切换 → 重新拉。
watch(boardPlatform, () => {
  void loadBoard();
});

// 任务切换（父组件复用本组件实例时 task prop 变）→ 全量刷新 + 关抽屉。
watch(
  () => props.task.id,
  () => {
    drillCell.value = null;
    boardPlatform.value = "";
    void reloadAll();
  },
);

onMounted(() => {
  void reloadAll();
});

// 暴露给父组件：SSE finished/failed 时刷新本页（避免父组件直接改本页 ref）。
defineExpose({ refresh: reloadAll });
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col overflow-y-auto" :style="{ gap: '20px' }">
    <!-- ════════ 1. 任务头 ════════ -->
    <section
      class="flex flex-shrink-0 flex-col"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '20px 22px',
        gap: '14px',
      }"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <button
            type="button"
            class="inline-flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '32px',
              height: '32px',
              borderRadius: '999px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              color: 'var(--ink-2)',
              cursor: 'pointer',
            }"
            title="返回卡位任务列表"
            @click="emit('back')"
          >
            <Icon name="arrowLeft" :size="15" />
          </button>
          <div class="min-w-0">
            <div class="text-[11px] uppercase" :style="{ letterSpacing: '1.2px', color: 'var(--ink-3)' }">
              AI 卡位 · 卡位仪表盘
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-2">
              <span class="font-display text-[18px] font-bold" :style="{ letterSpacing: '-0.3px' }">
                {{ brand || task.name }}
              </span>
              <span
                v-for="a in aliases"
                :key="a"
                class="rounded-full text-[10.5px]"
                :style="{ background: 'var(--card-2)', color: 'var(--ink-3)', padding: '2px 8px' }"
              >{{ a }}</span>
            </div>
          </div>
        </div>

        <!-- 运行 / 停止 / 编辑 / 删除 -->
        <div class="flex flex-shrink-0 items-center gap-2">
          <button
            v-if="!running"
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
            :style="{ background: 'var(--primary)', color: '#fff', borderRadius: '999px' }"
            title="立刻运行一次"
            @click="emit('run', task.id)"
          >
            <Icon name="play" :size="12" />
            <span>运行</span>
          </button>
          <button
            v-else
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
            :style="{
              background: 'var(--card-2)',
              color: 'var(--red, #d85a48)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
            }"
            title="停止监测"
            @click="emit('cancel', task.id)"
          >
            <Icon name="x" :size="12" />
            <span>停止</span>
          </button>
          <button
            type="button"
            class="inline-flex h-8 w-8 items-center justify-center"
            :style="{ borderRadius: '999px', background: 'var(--card-2)', border: '1px solid var(--line)', color: 'var(--ink-3)', cursor: 'pointer' }"
            title="编辑任务"
            @click="emit('edit', task)"
          >
            <Icon name="edit" :size="14" />
          </button>
          <button
            type="button"
            class="inline-flex h-8 w-8 items-center justify-center"
            :style="{ borderRadius: '999px', background: 'var(--card-2)', border: '1px solid var(--line)', color: 'var(--ink-3)', cursor: 'pointer' }"
            title="删除任务"
            @click="emit('delete', task.id)"
          >
            <Icon name="trash" :size="14" />
          </button>
        </div>
      </div>

      <!-- 关键词 / 平台 / 联网 / 上次运行 meta -->
      <div class="flex flex-wrap items-center" :style="{ gap: '8px 18px' }">
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">关键词</span>
          <template v-if="configKeywords.length">
            <span
              v-for="kw in configKeywords"
              :key="kw"
              class="rounded-full text-[11px]"
              :style="{ background: 'var(--card-2)', color: 'var(--ink-2)', padding: '2px 9px' }"
            >{{ kw }}</span>
          </template>
          <span v-else class="text-[11px]" :style="{ color: 'var(--ink-3)' }">—</span>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">平台</span>
          <template v-if="configPlatforms.length">
            <Pill v-for="p in configPlatforms" :key="p" tone="primary">{{ platformLabel(p) }}</Pill>
          </template>
          <span v-else class="text-[11px]" :style="{ color: 'var(--ink-3)' }">—</span>
        </div>
        <div class="flex items-center gap-1.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          <Icon name="clock" :size="12" />
          <span>上次运行 {{ lastRunText }}</span>
        </div>
        <div class="flex items-center gap-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          <span>联网检索</span>
          <span :style="{ color: webSearch ? 'var(--green)' : 'var(--ink-3)' }">
            {{ webSearch ? "开" : "关" }}
          </span>
        </div>
      </div>

      <!-- 运行中进度条 -->
      <div v-if="running" class="flex flex-col gap-1.5">
        <div class="flex items-center justify-between text-[11px]" :style="{ color: 'var(--ink-3)' }">
          <span>正在采集各平台回答…</span>
          <span v-if="monitorStatus.progressOf(task.id)">
            {{ monitorStatus.progressOf(task.id)!.current }} /
            {{ monitorStatus.progressOf(task.id)!.total }}
          </span>
        </div>
        <ProgressBar :value="progressRatio()" :height="6" />
      </div>
    </section>

    <!-- ════════ 2. 4 KPI 卡 ════════ -->
    <div class="grid flex-shrink-0 gap-4" :style="{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }">
      <!-- 曝光度 SoC -->
      <div
        :style="{ padding: '16px', borderRadius: '14px', background: 'var(--card)', border: '1px solid var(--line)' }"
      >
        <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">曝光度 SoC</div>
        <div class="mt-1.5 flex items-baseline gap-2">
          <span
            class="font-display font-bold"
            :style="{ fontSize: '26px', color: bandColor(latest?.metric?.status_band) }"
          >{{ latest ? pct(latest.metric?.soc) : "—" }}</span>
          <span
            v-if="latest?.metric?.status_band"
            class="text-[11px]"
            :style="{ color: bandColor(latest.metric.status_band) }"
          >{{ bandLabel(latest.metric.status_band) }}</span>
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          <template v-if="latest">
            {{ latest.metric?.mentioned ?? 0 }}/{{ latest.metric?.ok_total ?? 0 }} 有效
          </template>
          <template v-else>暂无数据</template>
        </div>
      </div>
      <!-- 首推率 -->
      <div
        :style="{ padding: '16px', borderRadius: '14px', background: 'var(--card)', border: '1px solid var(--line)' }"
      >
        <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">首推率</div>
        <div class="font-display mt-1.5 font-bold" :style="{ fontSize: '26px' }">
          {{ latest ? pct(latest.metric?.first_rank_rate) : "—" }}
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">AI 把你放第 1 的比例</div>
      </div>
      <!-- 净情感 -->
      <div
        :style="{ padding: '16px', borderRadius: '14px', background: 'var(--card)', border: '1px solid var(--line)' }"
      >
        <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">净情感</div>
        <div class="font-display mt-1.5 font-bold" :style="{ fontSize: '26px' }">
          {{ latest ? sentimentText(latest.metric?.sentiment_score) : "—" }}
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">提及处情感均值 (−1~1)</div>
      </div>
      <!-- 采集失败 -->
      <div
        :style="{ padding: '16px', borderRadius: '14px', background: 'var(--card)', border: '1px solid var(--line)' }"
      >
        <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">采集失败</div>
        <div class="font-display mt-1.5 font-bold" :style="{ fontSize: '26px' }">
          <template v-if="latest">
            <span
              v-if="(latest.metric?.error_cells ?? 0) > 0"
              :style="{ color: 'var(--red, #d85a48)' }"
            >{{ latest.metric!.error_cells }}</span>
            <span v-else :style="{ color: 'var(--green)', fontSize: '20px' }">0</span>
          </template>
          <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">够不到平台 / 被拦的格子</div>
      </div>
    </div>

    <!-- ════════ 3. 卡位矩阵（核心）════════ -->
    <section
      class="flex flex-shrink-0 flex-col overflow-hidden"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '20px 22px',
      }"
    >
      <div class="mb-3 flex items-center justify-between">
        <div>
          <div class="font-display text-[14px] font-semibold">卡位矩阵</div>
          <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
            点任意格子看 AI 原文 · 谁排在你前面 · 引用了哪些来源
          </div>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1 text-[11px]"
          :style="{ color: 'var(--ink-3)', background: 'transparent', cursor: 'pointer' }"
          title="刷新矩阵"
          @click="loadCells"
        >
          <Icon name="refresh" :size="11" />
          <span>刷新</span>
        </button>
      </div>

      <div
        v-if="cellsLoading"
        class="py-10 text-center text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >加载中…</div>
      <div
        v-else-if="matrixKeywords.length === 0 || matrixPlatforms.length === 0"
        class="py-10 text-center text-[12.5px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        还没有卡位数据 · 点右上「运行」采集一次后，关键词 × 平台矩阵会显示在这里。
      </div>

      <div v-else class="overflow-x-auto">
        <table class="w-full" :style="{ borderCollapse: 'separate', borderSpacing: '6px' }">
          <thead>
            <tr>
              <th
                class="text-left text-[11px] uppercase"
                :style="{ letterSpacing: '1px', color: 'var(--ink-3)', fontWeight: 500, padding: '4px 8px', minWidth: '120px' }"
              >关键词 \ 平台</th>
              <th
                v-for="p in matrixPlatforms"
                :key="p"
                class="text-center text-[12px]"
                :style="{ color: 'var(--ink-2)', fontWeight: 600, padding: '4px 8px', minWidth: '96px' }"
              >{{ platformLabel(p) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="kw in matrixKeywords" :key="kw">
              <td
                class="text-[12.5px] font-medium"
                :style="{ padding: '8px', color: 'var(--ink)', maxWidth: '200px' }"
              >
                <div class="truncate" :title="kw">{{ kw }}</div>
              </td>
              <td
                v-for="p in matrixPlatforms"
                :key="p"
                :style="{ padding: '0' }"
              >
                <!-- grid cell —— 查表命中才渲染内容 -->
                <template v-if="cellAt(kw, p)">
                  <button
                    type="button"
                    class="flex w-full flex-col items-center justify-center gap-1 transition"
                    :style="{
                      minHeight: '52px',
                      padding: '8px 6px',
                      borderRadius: '10px',
                      border: '1px solid var(--line)',
                      background: 'var(--card-2)',
                      cursor: 'pointer',
                    }"
                    :title="`${kw} · ${platformLabel(p)} — 点击下钻`"
                    @click="openDrill(cellAt(kw, p))"
                    @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.borderColor = 'var(--primary)')"
                    @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.borderColor = 'var(--line)')"
                  >
                    <!-- 采集失败 / 被拦 -->
                    <template v-if="isFailed(cellAt(kw, p)!)">
                      <span
                        class="inline-flex items-center gap-1 text-[11.5px] font-medium"
                        :style="{ color: cellAt(kw, p)!.status === 'blocked' ? 'var(--primary-deep, #c9521f)' : 'var(--red, #d85a48)' }"
                      >
                        <Icon name="warn" :size="11" />
                        采集失败
                      </span>
                    </template>
                    <!-- 未提及 -->
                    <template v-else-if="!isMentioned(cellAt(kw, p)!)">
                      <span class="text-[12px]" :style="{ color: 'var(--ink-3)' }">未提及</span>
                    </template>
                    <!-- 提及 → rank 徽章 + 情感点 -->
                    <template v-else>
                      <span class="inline-flex items-center gap-1.5">
                        <span
                          class="font-display text-[13px] font-bold"
                          :style="{ color: 'var(--ink)' }"
                        >
                          {{ cellAt(kw, p)!.rank > 0 ? `#${cellAt(kw, p)!.rank}` : "提及" }}
                        </span>
                        <span
                          :style="{
                            width: '8px',
                            height: '8px',
                            borderRadius: '999px',
                            background: sentimentDot(cellAt(kw, p)!.sentiment),
                            flexShrink: 0,
                          }"
                          :title="sentimentLabel(cellAt(kw, p)!.sentiment)"
                        />
                      </span>
                    </template>
                  </button>
                </template>
                <!-- 该 (kw,平台) 这次没跑（config 里有但矩阵没数据）-->
                <template v-else>
                  <div
                    class="flex w-full items-center justify-center text-[11px]"
                    :style="{ minHeight: '52px', color: 'var(--ink-3)', opacity: 0.5 }"
                  >·</div>
                </template>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 图例 -->
        <div class="mt-3 flex flex-wrap items-center" :style="{ gap: '6px 16px', color: 'var(--ink-3)' }">
          <span class="text-[10.5px]">图例</span>
          <span class="inline-flex items-center gap-1 text-[11px]">
            <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: 'var(--green)' }" />正面
          </span>
          <span class="inline-flex items-center gap-1 text-[11px]">
            <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: 'var(--ink-3)' }" />中性
          </span>
          <span class="inline-flex items-center gap-1 text-[11px]">
            <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: 'var(--red, #d85a48)' }" />负面
          </span>
          <span class="text-[11px]">#N = AI 推荐里你的排名</span>
        </div>
      </div>
    </section>

    <!-- ════════ 4. 信源聚合榜 ════════ -->
    <section
      class="flex min-h-0 flex-shrink-0 flex-col overflow-hidden"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '20px 22px',
      }"
    >
      <div class="mb-3 flex items-center justify-between gap-3">
        <div>
          <div class="font-display text-[14px] font-semibold">信源聚合榜 · 近 30 天</div>
          <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
            AI 回答引用最多的来源域名 —— 想被 AI 引用，先去这些源卡位
          </div>
        </div>
        <div class="flex items-center gap-2">
          <!-- 平台过滤 -->
          <select
            v-model="boardPlatform"
            class="text-[12px]"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
              color: 'var(--ink-2)',
              padding: '5px 10px',
              cursor: 'pointer',
            }"
          >
            <option value="">全部平台</option>
            <option v-for="p in matrixPlatforms" :key="p" :value="p">{{ platformLabel(p) }}</option>
          </select>
          <button
            type="button"
            class="inline-flex items-center gap-1 text-[11px]"
            :style="{ color: 'var(--ink-3)', background: 'transparent', cursor: 'pointer' }"
            title="刷新信源榜"
            @click="loadBoard"
          >
            <Icon name="refresh" :size="11" />
            <span>刷新</span>
          </button>
        </div>
      </div>

      <div
        v-if="boardLoading"
        class="py-8 text-center text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >加载中…</div>
      <div
        v-else-if="board.length === 0"
        class="py-8 text-center text-[12px]"
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
            <th class="py-1.5 text-left" :style="{ fontWeight: 500 }">命中关键词</th>
            <th class="py-1.5 text-right" :style="{ fontWeight: 500 }">频次</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in board"
            :key="row.domain + ' ' + row.source_type"
            :style="{ borderTop: '1px solid var(--line)' }"
          >
            <td class="py-2 text-[12.5px] font-medium" :style="{ maxWidth: '220px' }">
              <div class="truncate" :title="row.domain">{{ row.domain || "—" }}</div>
            </td>
            <td class="py-2">
              <Pill tone="info">{{ row.source_type }}</Pill>
            </td>
            <td class="py-2 text-[11.5px]" :style="{ color: 'var(--ink-2)', maxWidth: '260px' }">
              <div class="truncate" :title="row.keywords.join('、')">
                {{ row.keywords.length ? row.keywords.join("、") : "—" }}
              </div>
            </td>
            <td class="py-2 text-right font-display text-[13px] font-bold">{{ row.count }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 「去引流中心」占位（沿用 GeoTaskModule 习惯：暂作引导）-->
      <div class="mt-3 flex justify-end">
        <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
          想把这些源拿下？引流中心规划中…
        </span>
      </div>
    </section>

    <!-- ════════ 下钻抽屉（点矩阵格子）════════ -->
    <div
      v-if="drillCell"
      class="fixed inset-0 z-50 flex justify-end"
      :style="{ background: 'rgba(20,16,12,0.42)' }"
      @click.self="closeDrill"
    >
      <div
        class="flex h-full w-full max-w-[520px] flex-col overflow-hidden"
        :style="{ background: 'var(--card)', borderLeft: '1px solid var(--line)', boxShadow: '-12px 0 40px rgba(0,0,0,0.18)' }"
      >
        <!-- 抽屉头 -->
        <div
          class="flex flex-shrink-0 items-start justify-between gap-3"
          :style="{ padding: '18px 20px', borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0">
            <div class="text-[11px] uppercase" :style="{ letterSpacing: '1.2px', color: 'var(--ink-3)' }">
              卡位下钻
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-2">
              <span class="font-display text-[15px] font-bold">{{ drillCell.keyword }}</span>
              <Pill tone="primary">{{ platformLabel(drillCell.platform) }}</Pill>
            </div>
          </div>
          <button
            type="button"
            class="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center"
            :style="{ borderRadius: '999px', background: 'var(--card-2)', border: '1px solid var(--line)', color: 'var(--ink-3)', cursor: 'pointer' }"
            title="关闭"
            @click="closeDrill"
          >
            <Icon name="x" :size="15" />
          </button>
        </div>

        <!-- 抽屉体 -->
        <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto" :style="{ padding: '18px 20px' }">
          <!-- 状态条：排名 / 情感 / 状态 -->
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="inline-flex items-center gap-1.5 rounded-full text-[12px] font-medium"
              :style="{ background: 'var(--card-2)', border: '1px solid var(--line)', padding: '4px 11px' }"
            >
              <span :style="{ color: 'var(--ink-3)' }">排名</span>
              <span class="font-display font-bold">
                {{ isMentioned(drillCell) ? (drillCell.rank > 0 ? `#${drillCell.rank}` : "已提及") : "未提及" }}
              </span>
            </span>
            <span
              class="inline-flex items-center gap-1.5 rounded-full text-[12px]"
              :style="{ background: 'var(--card-2)', border: '1px solid var(--line)', padding: '4px 11px' }"
            >
              <span
                :style="{ width: '8px', height: '8px', borderRadius: '999px', background: sentimentDot(drillCell.sentiment) }"
              />
              <span :style="{ color: 'var(--ink-2)' }">{{ sentimentLabel(drillCell.sentiment) }}</span>
            </span>
            <Pill :tone="drillCell.status === 'ok' ? 'ok' : drillCell.status === 'blocked' ? 'warn' : drillCell.status === 'error' ? 'alert' : 'info'">
              {{ statusLabel(drillCell.status) }}
            </Pill>
          </div>

          <!-- 推荐顺序（高亮 is_target = 你的品牌）-->
          <div>
            <div class="mb-2 text-[12px] font-semibold">推荐顺序 · 谁排在你前面</div>
            <div
              v-if="drillCell.recommended.length === 0"
              class="text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >这次回答未给出明确的推荐列表。</div>
            <div v-else class="flex flex-col gap-1.5">
              <div
                v-for="r in drillCell.recommended"
                :key="r.position + ' ' + r.name"
                class="flex items-center gap-2.5"
                :style="{
                  padding: '8px 11px',
                  borderRadius: '10px',
                  background: r.is_target ? 'var(--primary-soft)' : 'var(--card-2)',
                  border: r.is_target ? '1px solid var(--primary)' : '1px solid var(--line)',
                }"
              >
                <span
                  class="inline-flex flex-shrink-0 items-center justify-center font-display text-[12px] font-bold"
                  :style="{
                    width: '22px',
                    height: '22px',
                    borderRadius: '999px',
                    background: r.is_target ? 'var(--primary)' : 'var(--card)',
                    color: r.is_target ? '#fff' : 'var(--ink-2)',
                  }"
                >{{ r.position }}</span>
                <span
                  class="truncate text-[13px]"
                  :style="{ color: r.is_target ? 'var(--primary-deep, #c9521f)' : 'var(--ink)', fontWeight: r.is_target ? 700 : 500 }"
                  :title="r.name"
                >{{ r.name }}</span>
                <span
                  v-if="r.is_target"
                  class="ml-auto flex-shrink-0 rounded-full text-[10px] font-medium"
                  :style="{ background: 'var(--primary)', color: '#fff', padding: '1px 7px' }"
                >你的品牌</span>
              </div>
            </div>
          </div>

          <!-- AI 原文 -->
          <div>
            <div class="mb-2 flex items-center gap-2">
              <div class="text-[12px] font-semibold">AI 原文</div>
              <span v-if="drillCell.summary" class="text-[11px]" :style="{ color: 'var(--ink-3)' }">· {{ drillCell.summary }}</span>
            </div>
            <div
              class="whitespace-pre-wrap text-[12.5px] leading-relaxed"
              :style="{
                color: 'var(--ink-2)',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
                borderRadius: '10px',
                padding: '12px 14px',
                maxHeight: '260px',
                overflowY: 'auto',
              }"
            >{{ drillCell.answer_text || "（无原文 —— 该平台未返回可见回答）" }}</div>
          </div>

          <!-- 引用信源 -->
          <div>
            <div class="mb-2 text-[12px] font-semibold">
              引用信源
              <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">（{{ drillCell.citations.length }}）</span>
            </div>
            <div
              v-if="drillCell.citations.length === 0"
              class="text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >这次回答未引用可识别的来源。</div>
            <div v-else class="flex flex-col gap-1.5">
              <a
                v-for="(c, ci) in drillCell.citations"
                :key="ci"
                :href="c.url || undefined"
                target="_blank"
                rel="noopener noreferrer"
                class="flex flex-col gap-0.5"
                :style="{
                  padding: '9px 11px',
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                  textDecoration: 'none',
                }"
              >
                <div class="flex items-center gap-2">
                  <Pill tone="info">{{ c.source_type }}</Pill>
                  <span class="truncate text-[12px] font-medium" :style="{ color: 'var(--ink)' }" :title="c.domain">
                    {{ c.domain || "—" }}
                  </span>
                </div>
                <span
                  v-if="c.title"
                  class="truncate text-[11.5px]"
                  :style="{ color: 'var(--ink-2)' }"
                  :title="c.title"
                >{{ c.title }}</span>
                <span class="truncate text-[10.5px]" :style="{ color: 'var(--ink-3)' }" :title="c.url">{{ c.url }}</span>
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
