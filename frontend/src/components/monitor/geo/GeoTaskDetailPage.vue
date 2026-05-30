<script setup lang="ts">
/**
 * GEO「AI 卡位」L2 详情页 —— 百度排名 L2 同款双卡布局（左关键词列表 + 右详情）。
 * 在 GeoTaskModule 的任务列表里点**多关键词任务**的任务名钻入（单关键词任务
 * 不进二级页，详情内联在 L1 右侧）；返回按钮还原列表，跟 BaiduRankingPage 的
 * Level 1→2 同手势。
 *
 * 布局（镜像 BaiduRankingPage Level 2）：
 *   - 顶部卡头：← 返回 · 「AI 卡位 · 关键词列表」+ 品牌名 · [N 个关键词] 徽章。
 *   - 左卡：关键词列表 —— 一行一个关键词，列 = 关键词 | 每平台一列（该词在该
 *     平台的紧凑卡位指标 #rank / 未提及 / ⚠失败）| 状态。行可点（选中高亮）。
 *   - 右卡：
 *       默认（未选关键词）= 任务汇总：4 KPI 卡（SoC 含 ok_total/total 副标 + 色带
 *         / 首推率 / 净情感 / 采集失败）+ 信源聚合榜（带平台过滤）。
 *       点关键词 → 渲染该关键词的「单关键词 · 多平台详情」可复用块
 *         （GeoKeywordPlatformDetail，L1 内联也用同一块）。
 *
 * 自包含（IA 大改会整体搬走）：自己拉
 *   - 最近一次 result.metric（GET /api/monitor/results?task_id=&limit=1）→ 4 KPI。
 *   - 最近一跑的全部 cell（GET /api/monitor/geo/{id}/latest-cells）→ 关键词列表
 *     + 右侧多平台详情。
 *   - 信源聚合榜（GET /api/monitor/geo/{id}/citations?days=&platform=）带平台过滤。
 *
 * 运行 / 编辑 / 删除 / 停止 不在本页直接调接口，emit 给父组件复用其既有处理。
 * 视觉沿用 BaiduRankingPage / GeoTaskModule 的设计系统 idiom，不另造观感。
 */
import { computed, onMounted, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import GeoKeywordPlatformDetail from "@/components/monitor/geo/GeoKeywordPlatformDetail.vue";
import type { GeoCellRow } from "@/components/monitor/geo/GeoKeywordPlatformDetail.vue";

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

// ── 类型（与后端 metric 形状对齐；cell 形状复用子组件的 GeoCellRow）──────
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

// ── 状态 ───────────────────────────────────────────────────────────────
const latest = ref<LatestResult | null>(null);
const cells = ref<GeoCellRow[]>([]);
const cellsLoading = ref(false);

const board = ref<CitationRow[]>([]);
const boardLoading = ref(false);
// 信源榜平台过滤（'' = 全部）。
const boardPlatform = ref<string>("");

// 左卡选中关键词（null = 右卡显示任务汇总；非 null = 显示该关键词多平台详情）。
const selectedKeyword = ref<string | null>(null);

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

// ── 关键词列表 / 平台列：从 config ∪ cells 派生 ──────────────────────────
// 平台列优先用 config.platforms（保证空跑也成列），并补 cells 里出现但 config
// 没有的；关键词行优先 config.keywords，同样补 cells 里出现的。
const matrixPlatforms = computed<string[]>(() => {
  const seen = new Set<string>(configPlatforms.value);
  for (const c of cells.value) seen.add(c.platform);
  return Array.from(seen);
});
const keywordList = computed<string[]>(() => {
  const seen = new Set<string>(configKeywords.value);
  for (const c of cells.value) seen.add(c.keyword);
  return Array.from(seen);
});

// (keyword, platform) → cell 快速查表。
const cellIndex = computed<Map<string, GeoCellRow>>(() => {
  const m = new Map<string, GeoCellRow>();
  for (const c of cells.value) m.set(`${c.keyword}|${c.platform}`, c);
  return m;
});
function cellAt(keyword: string, platform: string): GeoCellRow | null {
  return cellIndex.value.get(`${keyword}|${platform}`) ?? null;
}

// 某关键词的全部平台 cell（喂给 GeoKeywordPlatformDetail）。
function cellsForKeyword(keyword: string): GeoCellRow[] {
  return cells.value.filter((c) => c.keyword === keyword);
}
const selectedKeywordCells = computed<GeoCellRow[]>(() =>
  selectedKeyword.value ? cellsForKeyword(selectedKeyword.value) : [],
);

function isMentioned(c: GeoCellRow): boolean {
  return c.mentioned === true || c.mentioned === 1;
}
function isFailed(c: GeoCellRow): boolean {
  return c.status === "error" || c.status === "blocked";
}

// 某关键词行的「状态」徽章 —— 优先级：该词这次没跑 → 未跑；全平台失败 →
// 采集失败；任一平台提及 → 已卡位；有失败但也有非失败结果 → 部分失败；
// 有数据但全未提及 → 未提及。
function keywordRowStatus(keyword: string): { label: string; tone: "ok" | "warn" | "alert" | "info" } {
  const rows = cellsForKeyword(keyword);
  if (rows.length === 0) return { label: "未跑", tone: "info" };
  if (rows.every((c) => isFailed(c))) return { label: "采集失败", tone: "alert" };
  if (rows.some((c) => isMentioned(c))) return { label: "已卡位", tone: "ok" };
  if (rows.some((c) => isFailed(c))) return { label: "部分失败", tone: "warn" };
  return { label: "未提及", tone: "alert" };
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

function selectKeyword(keyword: string): void {
  selectedKeyword.value = keyword;
}
function clearKeyword(): void {
  selectedKeyword.value = null;
}

// 信源榜平台过滤切换 → 重新拉。
watch(boardPlatform, () => {
  void loadBoard();
});

// 任务切换（父组件复用本组件实例时 task prop 变）→ 全量刷新 + 清选中。
watch(
  () => props.task.id,
  () => {
    selectedKeyword.value = null;
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
  <div class="flex min-h-0 flex-1 flex-col" :style="{ gap: '16px' }">
    <!-- ════════ 顶部卡头：返回 + 品牌 + N 个关键词徽章 + 运行/编辑/删除 ════════ -->
    <section
      class="flex flex-shrink-0 flex-col"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '18px 22px',
        gap: '12px',
      }"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
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
            title="返回卡位任务列表"
            @click="emit('back')"
          >
            <Icon name="arrowLeft" :size="14" />
          </button>
          <div class="min-w-0">
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
              AI 卡位 · 关键词列表
            </div>
            <div class="mt-0.5 flex flex-wrap items-center gap-2">
              <span class="font-display text-[16px] font-bold" :style="{ letterSpacing: '-0.3px' }">
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

        <!-- 右侧：N 个关键词徽章 + 运行 / 停止 / 编辑 / 删除 -->
        <div class="flex flex-shrink-0 items-center gap-2">
          <span
            class="text-[11px]"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
              color: 'var(--ink-3)',
              padding: '4px 11px',
            }"
          >{{ keywordList.length }} 个关键词</span>
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

      <!-- 平台 / 联网 / 上次运行 meta -->
      <div class="flex flex-wrap items-center" :style="{ gap: '8px 18px' }">
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

    <!-- ════════ 双卡：左关键词列表 + 右详情 ════════ -->
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
        <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
          <div class="min-w-0">
            <div class="font-display text-[14px] font-semibold">关键词列表</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              点关键词看各平台 AI 卡位详情
            </div>
          </div>
          <button
            type="button"
            class="inline-flex flex-shrink-0 items-center gap-1 text-[11px]"
            :style="{ color: 'var(--ink-3)', background: 'transparent', cursor: 'pointer' }"
            title="刷新关键词列表"
            @click="loadCells"
          >
            <Icon name="refresh" :size="11" />
            <span>刷新</span>
          </button>
        </div>

        <!-- 列头：关键词 | 每平台一列 | 状态（固定在滚动区外）-->
        <div
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: `1.6fr repeat(${matrixPlatforms.length}, minmax(64px, .8fr)) .7fr`,
            letterSpacing: '1px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
            gap: '4px',
          }"
        >
          <div>关键词</div>
          <div v-for="p in matrixPlatforms" :key="p" class="truncate text-center" :title="platformLabel(p)">
            {{ platformLabel(p) }}
          </div>
          <div class="text-center">状态</div>
        </div>

        <!-- 数据行（只含数据行，列头已上移到滚动区外）-->
        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div
            v-if="cellsLoading"
            class="py-10 text-center text-[12px]"
            :style="{ color: 'var(--ink-3)' }"
          >加载中…</div>

          <div
            v-else-if="keywordList.length === 0"
            class="py-10 text-center text-[12.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            此任务未配置关键词 · 编辑任务添加关键词后运行采集。
          </div>

          <template v-else>
            <div
              v-for="(kw, i) in keywordList"
              :key="kw"
              class="grid cursor-pointer items-center transition"
              :style="{
                gridTemplateColumns: `1.6fr repeat(${matrixPlatforms.length}, minmax(64px, .8fr)) .7fr`,
                borderBottom: i < keywordList.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '12px 8px',
                gap: '4px',
                background: selectedKeyword === kw ? 'var(--card-2)' : 'transparent',
              }"
              @click="selectKeyword(kw)"
              @mouseenter="(e) => { if (selectedKeyword !== kw) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
              @mouseleave="(e) => { if (selectedKeyword !== kw) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
            >
              <!-- 关键词 -->
              <div class="min-w-0">
                <div class="truncate text-[12.5px] font-medium" :style="{ color: 'var(--ink)' }" :title="kw">
                  {{ kw }}
                </div>
              </div>

              <!-- 每平台一列：紧凑卡位指标 -->
              <div v-for="p in matrixPlatforms" :key="p" class="flex items-center justify-center">
                <template v-if="cellAt(kw, p)">
                  <!-- 采集失败 -->
                  <span
                    v-if="isFailed(cellAt(kw, p)!)"
                    class="inline-flex items-center"
                    :style="{ color: cellAt(kw, p)!.status === 'blocked' ? 'var(--primary-deep, #c9521f)' : 'var(--red, #d85a48)' }"
                    :title="cellAt(kw, p)!.status === 'blocked' ? '被拦截' : '采集失败'"
                  >
                    <Icon name="warn" :size="12" />
                  </span>
                  <!-- 未提及 -->
                  <span
                    v-else-if="!isMentioned(cellAt(kw, p)!)"
                    class="text-[11px]"
                    :style="{ color: 'var(--ink-3)' }"
                  >未提及</span>
                  <!-- 提及 → #rank + 情感点 -->
                  <span v-else class="inline-flex items-center gap-1">
                    <span class="font-display text-[12.5px] font-bold" :style="{ color: 'var(--primary-deep)' }">
                      {{ cellAt(kw, p)!.rank > 0 ? `#${cellAt(kw, p)!.rank}` : "提及" }}
                    </span>
                    <span
                      :style="{ width: '7px', height: '7px', borderRadius: '999px', background: sentimentDot(cellAt(kw, p)!.sentiment), flexShrink: 0 }"
                    />
                  </span>
                </template>
                <!-- 该 (kw,平台) 这次没跑 -->
                <span v-else class="text-[11px]" :style="{ color: 'var(--ink-3)', opacity: 0.5 }">·</span>
              </div>

              <!-- 状态 -->
              <div class="flex items-center justify-center">
                <Pill :tone="keywordRowStatus(kw).tone">{{ keywordRowStatus(kw).label }}</Pill>
              </div>
            </div>
          </template>
        </div>
      </section>

      <!-- ── 右卡：任务汇总（默认）/ 单关键词多平台详情（点关键词后）──── -->
      <section
        class="flex min-h-0 flex-col overflow-y-auto"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <!-- 卡头：随选中态切标题 -->
        <div class="mb-3 flex flex-shrink-0 items-start justify-between gap-2">
          <div class="min-w-0">
            <template v-if="!selectedKeyword">
              <div class="font-display text-[14px] font-semibold">任务汇总</div>
              <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                全部关键词 × 平台的卡位概览 + 信源
              </div>
            </template>
            <template v-else>
              <div class="font-display text-[14px] font-semibold">多平台详情</div>
              <div class="mt-0.5 truncate text-[11.5px]" :style="{ color: 'var(--ink-3)' }" :title="selectedKeyword">
                关键词：{{ selectedKeyword }}
              </div>
            </template>
          </div>
          <button
            v-if="selectedKeyword"
            type="button"
            class="inline-flex flex-shrink-0 items-center gap-1 text-[11.5px]"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
              color: 'var(--ink-2)',
              padding: '4px 11px',
              cursor: 'pointer',
            }"
            title="返回任务汇总"
            @click="clearKeyword"
          >
            <Icon name="arrowLeft" :size="11" />
            <span>任务汇总</span>
          </button>
        </div>

        <!-- ════ 默认：任务汇总（4 KPI + 信源榜）════ -->
        <template v-if="!selectedKeyword">
          <!-- 4 KPI（2×2）-->
          <div class="grid flex-shrink-0 grid-cols-2 gap-3">
            <!-- 曝光度 SoC + 色带 + ok_total/total 副标 -->
            <div :style="{ padding: '14px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
              <div class="text-[10.5px] uppercase" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">曝光度 SoC</div>
              <div class="mt-1 flex items-baseline gap-2">
                <span class="font-display font-bold" :style="{ fontSize: '22px', color: bandColor(latest?.metric?.status_band) }">
                  {{ latest ? pct(latest.metric?.soc) : "—" }}
                </span>
                <span
                  v-if="latest?.metric?.status_band"
                  class="text-[11px]"
                  :style="{ color: bandColor(latest.metric.status_band) }"
                >{{ bandLabel(latest.metric.status_band) }}</span>
              </div>
              <div class="mt-1 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                <template v-if="latest">{{ latest.metric?.ok_total ?? 0 }}/{{ latest.metric?.total ?? 0 }} 有效格子</template>
                <template v-else>暂无数据</template>
              </div>
            </div>
            <!-- 首推率 -->
            <div :style="{ padding: '14px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
              <div class="text-[10.5px] uppercase" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">首推率</div>
              <div class="font-display mt-1 font-bold" :style="{ fontSize: '22px' }">
                {{ latest ? pct(latest.metric?.first_rank_rate) : "—" }}
              </div>
              <div class="mt-1 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">AI 把你放第 1 的比例</div>
            </div>
            <!-- 净情感 -->
            <div :style="{ padding: '14px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
              <div class="text-[10.5px] uppercase" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">净情感</div>
              <div class="font-display mt-1 font-bold" :style="{ fontSize: '22px' }">
                {{ latest ? sentimentText(latest.metric?.sentiment_score) : "—" }}
              </div>
              <div class="mt-1 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">提及处情感均值 (−1~1)</div>
            </div>
            <!-- 采集失败 -->
            <div :style="{ padding: '14px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
              <div class="text-[10.5px] uppercase" :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }">采集失败</div>
              <div class="font-display mt-1 font-bold" :style="{ fontSize: '22px' }">
                <template v-if="latest">
                  <span v-if="(latest.metric?.error_cells ?? 0) > 0" :style="{ color: 'var(--red, #d85a48)' }">
                    {{ latest.metric!.error_cells }} 个
                  </span>
                  <span v-else :style="{ color: 'var(--green)', fontSize: '16px' }">全部成功</span>
                </template>
                <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
              </div>
              <div class="mt-1 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">够不到平台 / 被拦的格子</div>
            </div>
          </div>

          <!-- 还没跑过提示 -->
          <div
            v-if="!latest"
            class="mt-3 flex-shrink-0 text-[11.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            该任务还没有运行记录 · 点右上「运行」采集一次后显示卡位数据。
          </div>

          <!-- 引导：点左侧关键词看多平台详情（仿百度「点击左侧关键词查看排名详情」）-->
          <div
            class="mt-4 flex flex-shrink-0 items-center gap-2 rounded text-[11.5px]"
            :style="{ background: 'var(--card-2)', border: '1px dashed var(--line)', color: 'var(--ink-3)', padding: '10px 12px' }"
          >
            <Icon name="arrowLeft" :size="12" />
            <span>点击左侧关键词查看多平台详情（AI 原文 · 谁排在你前面 · 引用信源）</span>
          </div>

          <!-- ════ 信源聚合榜（近 30 天，带平台过滤）════ -->
          <div class="mt-5 flex min-h-0 flex-1 flex-col">
            <div class="mb-2 flex flex-shrink-0 items-center justify-between gap-2">
              <div class="text-[12px] font-semibold">信源聚合榜 · 近 30 天</div>
              <div class="flex items-center gap-2">
                <select
                  v-model="boardPlatform"
                  class="text-[11.5px]"
                  :style="{
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '999px',
                    color: 'var(--ink-2)',
                    padding: '4px 9px',
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
                  <tr class="text-[10.5px] uppercase" :style="{ letterSpacing: '1px', color: 'var(--ink-3)' }">
                    <th class="py-1.5 text-left" :style="{ fontWeight: 500 }">域名</th>
                    <th class="py-1.5 text-left" :style="{ fontWeight: 500 }">类型</th>
                    <th class="py-1.5 text-right" :style="{ fontWeight: 500 }">频次</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in board"
                    :key="row.domain + ' ' + row.source_type"
                    :style="{ borderTop: '1px solid var(--line)' }"
                  >
                    <td class="truncate py-2 text-[12.5px] font-medium" :style="{ maxWidth: '0' }" :title="row.domain">
                      {{ row.domain || "—" }}
                    </td>
                    <td class="py-2">
                      <Pill tone="info">{{ row.source_type }}</Pill>
                    </td>
                    <td class="py-2 text-right font-display text-[13px] font-bold">{{ row.count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- ════ 点关键词后：单关键词 · 多平台详情（复用块，L1 内联同款）════ -->
        <template v-else>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <GeoKeywordPlatformDetail :keyword="selectedKeyword" :cells="selectedKeywordCells" />
          </div>
        </template>
      </section>
    </div>
  </div>
</template>
