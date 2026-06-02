/**
 * GEO「AI 卡位」详情数据层 —— 把 design_handoff_geo_fullpage 的数据模型
 * （PLATFORMS / METRIC / HISTORY / COMPETITORS / BOARD + 衍生结论/teaser）
 * 从既有只读端点装配出来。**不改后端**：所有竞品聚合 / 摘录 / 平台引用率
 * 都在前端从 cells + result.metric.by_keyword + citation leaderboard 派生。
 *
 * 端点映射（详见 README §数据接线）：
 *   - GET /api/monitor/geo/{taskId}/latest-cells  → 该任务最近一跑全部 cell，
 *     按关键词过滤 → PLATFORMS[]。
 *   - GET /api/monitor/results?task_id=&limit=8    → results[]。
 *       METRIC   = results[0].metric.by_keyword[keyword]
 *       HISTORY  = 每个 result（按时间正序）的 by_keyword[keyword] 的 soc/first_rank_rate
 *   - GET /api/monitor/geo/{taskId}/citations?days=30&keyword=  → BOARD[]
 *   - COMPETITORS[] = 从 PLATFORMS 的 recommended[]（is_target=false）跨平台聚合。
 *
 * 纯函数 + 一个 composable。helper 对齐 geo-shared.jsx 的 cellStatus/bandColor 等。
 */
import { computed, ref, watch, type Ref } from "vue";

import { useSidecar } from "@/stores/sidecar";

// ── 平台标签（README：6 个平台的中文名）─────────────────────────────────
// GEO_PLATFORMS（monitor-types）目前只声明了 tongyi/kimi 两个上线平台，但
// cells 里可能出现后续接入的 doubao/deepseek/yuanbao/quark —— 这里给全 6 个
// 标签，落地时 cell.platform 取到哪个都能渲染中文名。
export const PLATFORM_LABELS: Record<string, string> = {
  tongyi: "通义千问",
  kimi: "Kimi",
  doubao: "豆包",
  deepseek: "DeepSeek",
  yuanbao: "腾讯元宝",
  quark: "夸克",
};
export function platformLabel(value: string): string {
  return PLATFORM_LABELS[value] ?? value;
}

// 热力矩阵表头用的短名（窄列）。
export const PLATFORM_SHORT: Record<string, string> = {
  tongyi: "千问",
  kimi: "Kimi",
  doubao: "豆包",
  deepseek: "DeepSeek",
  yuanbao: "元宝",
  quark: "夸克",
};
export function platformShort(value: string): string {
  return PLATFORM_SHORT[value] ?? PLATFORM_LABELS[value] ?? value;
}

// 信源专属调色板（chart-specific，README §Tokens 给的 SRC_COLORS）。
// 新增信源按序取下一个不同色。
export const SRC_COLORS = [
  "#ee6a2a", "#3a7ca5", "#7a9b5e", "#d85a48", "#9b6a9e",
  "#c2962f", "#3f9c8f", "#b5654d", "#5b6cb0", "#8a8f2f",
];
// 竞争「榜首」专用冷蓝（README §Tokens；style.css 没有，作 chart-local 常量）。
export const COMPETITOR_BLUE = "#3a6ea5";

// ── 衍生类型（与后端 cell / metric / leaderboard 对齐）──────────────────
export interface Cite {
  domain: string;
  type: string;
  title: string;
  url: string;
}
export interface RecommendedEntity {
  name: string;
  position: number;
  is_target: boolean;
}
/** 一个平台格（cell → 视图模型）。 */
export interface PlatformVM {
  id: string;
  name: string;
  status: string; // 'ok' | 'error' | 'blocked' | 'empty' ...
  mentioned: boolean;
  rank: number;
  sentiment: string; // 'pos' | 'neu' | 'neg' | 'na'
  citations: number;
  summary: string;
  answer: string;
  excerpt: string;
  recommended: RecommendedEntity[];
  cites: Cite[];
}
/** result.metric.by_keyword[keyword] 的形状（见 csm_core.monitor.geo.metrics._block）。 */
export interface KeywordMetric {
  total: number;
  ok_total: number;
  error_cells: number;
  mentioned: number;
  soc: number;
  status_band: string; // strong | weak | hidden
  first_rank_rate: number;
  first_rank_rate_mentioned: number;
  sentiment_score: number;
}
export interface HistoryPoint {
  date: string;
  soc: number;
  first: number;
}
export interface CompetitorVM {
  name: string;
  appears: number;
  avgRank: number;
}
export interface BoardRow {
  domain: string;
  type: string;
  count: number;
  platforms: number;
}

// ── helper（移植 geo-shared.jsx）─────────────────────────────────────────
export function pct(v: number | undefined | null): string {
  return typeof v !== "number" || Number.isNaN(v) ? "—" : `${Math.round(v * 100)}%`;
}
export function sentimentText(v: number | undefined | null): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}
export function bandColor(b: string | undefined): string {
  return b === "strong"
    ? "var(--green)"
    : b === "weak"
      ? "var(--primary-deep)"
      : "var(--red)";
}
export function bandLabel(b: string | undefined): string {
  return b === "strong"
    ? "强曝光"
    : b === "weak"
      ? "弱曝光"
      : b === "hidden"
        ? "未露出"
        : "—";
}
export function sentDotColor(s: string): string {
  return s === "pos"
    ? "var(--green)"
    : s === "neg"
      ? "var(--red)"
      : s === "neu"
        ? "var(--ink-3)"
        : "transparent";
}
export function sentLabel(s: string): string {
  return s === "pos" ? "正面" : s === "neg" ? "负面" : s === "neu" ? "中性" : "未判定";
}
export function isFailed(p: { status: string }): boolean {
  return p.status === "error" || p.status === "blocked";
}

export interface CellBadge {
  kind: "first" | "hit" | "miss" | "fail";
  label: string;
  short: string;
  color: string;
}
/** 平台单格状态徽章（移植 geo-shared.jsx cellStatus）。 */
export function cellStatus(p: PlatformVM): CellBadge {
  if (isFailed(p)) return { kind: "fail", label: "采集失败", short: "⚠ 失败", color: "var(--red)" };
  if (!p.mentioned) return { kind: "miss", label: "未提及", short: "✗ 未提及", color: "var(--red)" };
  if (p.rank === 1) return { kind: "first", label: "首推 #1", short: "★ #1", color: "var(--green)" };
  return { kind: "hit", label: `提及 #${p.rank}`, short: `#${p.rank}`, color: "var(--primary-deep)" };
}

// ── 原始 cell 形状（latest-cells 水合后；见 geo_storage._hydrate_cells）──
interface RawCite {
  url: string;
  title: string;
  domain: string;
  source_type: string;
}
interface RawCell {
  platform: string;
  keyword: string;
  mentioned: boolean | number;
  rank: number;
  sentiment: string;
  status: string;
  answer_text: string;
  citations: RawCite[];
  recommended: RecommendedEntity[];
  summary: string;
}

/**
 * 从 answer_text 截出「含品牌名那段」做摘录。把全文按中文/英文句末标点切句，
 * 取第一句命中 brand（或别名）的句子；命中不到回退 summary，再回退首句。
 * 品牌名在视图层（GeoPlatformBlock）再高亮，这里只负责选段。
 */
export function deriveExcerpt(
  answer: string,
  summary: string,
  brandTerms: string[],
): string {
  const text = (answer || "").trim();
  if (!text) return (summary || "").trim();
  const terms = brandTerms.map((t) => t.trim()).filter(Boolean);
  if (terms.length) {
    // 句子切分：在中文句末标点（。！？；）或英文 .!? 后断句，保留标点。
    const sentences = text
      .split(/(?<=[。！？；!?\.])\s*/)
      .map((s) => s.trim())
      .filter(Boolean);
    const hit = sentences.find((s) => terms.some((t) => s.includes(t)));
    if (hit) return hit;
  }
  // 没命中品牌 → summary 优先（人话总评），再退首句。
  if (summary && summary.trim()) return summary.trim();
  const first = text.split(/(?<=[。！？；!?\.])\s*/)[0];
  return (first || text).trim();
}

function cellToPlatform(c: RawCell, brandTerms: string[]): PlatformVM {
  const mentioned = c.mentioned === true || c.mentioned === 1;
  const cites: Cite[] = (c.citations ?? []).map((x) => ({
    domain: x.domain,
    type: x.source_type,
    title: x.title,
    url: x.url,
  }));
  return {
    id: c.platform,
    name: platformLabel(c.platform),
    status: c.status,
    mentioned,
    rank: typeof c.rank === "number" ? c.rank : -1,
    sentiment: c.sentiment || "na",
    citations: cites.length,
    summary: c.summary || "",
    answer: c.answer_text || "",
    excerpt: mentioned ? deriveExcerpt(c.answer_text || "", c.summary || "", brandTerms) : "",
    recommended: Array.isArray(c.recommended) ? c.recommended : [],
    cites,
  };
}

/**
 * 跨平台竞品聚合（README）：对每个 recommended 实体（is_target=false），
 * 按 name 归组 → {name, appears=出现的不同平台数, avgRank=出现平台位次均值}。
 * appears 降序、avgRank 升序。"榜首" = avgRank 最小（并列取 appears 多）。
 */
export function deriveCompetitors(platforms: PlatformVM[]): CompetitorVM[] {
  const byName = new Map<string, { plats: Set<string>; ranks: number[] }>();
  for (const p of platforms) {
    for (const r of p.recommended) {
      if (r.is_target) continue;
      const name = (r.name || "").trim();
      if (!name) continue;
      const e = byName.get(name) ?? { plats: new Set<string>(), ranks: [] };
      e.plats.add(p.id);
      if (typeof r.position === "number" && r.position > 0) e.ranks.push(r.position);
      byName.set(name, e);
    }
  }
  const out: CompetitorVM[] = [];
  for (const [name, e] of byName) {
    const appears = e.plats.size;
    const avgRank = e.ranks.length
      ? e.ranks.reduce((a, b) => a + b, 0) / e.ranks.length
      : 0;
    out.push({ name, appears, avgRank });
  }
  out.sort((a, b) => (b.appears - a.appears) || (a.avgRank - b.avgRank));
  return out;
}

/** 你（云野）的平均位次（在提及你的平台上）—— 散点 Y 用。无提及回退 5（垫底）。 */
export function targetAvgRank(platforms: PlatformVM[]): number {
  const ranks: number[] = [];
  for (const p of platforms) {
    if (isFailed(p) || !p.mentioned) continue;
    if (typeof p.rank === "number" && p.rank > 0) ranks.push(p.rank);
  }
  return ranks.length ? ranks.reduce((a, b) => a + b, 0) / ranks.length : 5;
}
/** 你出现的（提及）平台数 —— 散点 X 用。 */
export function targetAppears(platforms: PlatformVM[]): number {
  return platforms.filter((p) => !isFailed(p) && p.mentioned).length;
}

// 上次运行时间本地化简写（详情头副标用）。
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "尚未运行";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "尚未运行";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
// HISTORY 趋势点的短日期（M/D）。
function fmtShortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

// ── 装配结果 ─────────────────────────────────────────────────────────────
export interface KeywordDetail {
  platforms: PlatformVM[];
  metric: KeywordMetric | null;
  history: HistoryPoint[];
  competitors: CompetitorVM[];
  board: BoardRow[];
  lastRunIso: string | null;
  /** 概览结论条文案（黄条）。 */
  conclusion: string;
  /** 头号对手名（teaser / 散点榜首），无则 ""。 */
  headCompetitor: string;
  /** 高权重信源域名（teaser），无则 ""。 */
  topSource: string;
}

// 平台排序：稳定展示顺序（先 GEO 既定顺序的 6 平台，再其余按名）。
const PLATFORM_ORDER = ["doubao", "tongyi", "yuanbao", "kimi", "deepseek", "quark"];
function orderPlatforms(arr: PlatformVM[]): PlatformVM[] {
  const idx = new Map(PLATFORM_ORDER.map((v, i) => [v, i]));
  return [...arr].sort((a, b) => {
    const ia = idx.has(a.id) ? idx.get(a.id)! : 999;
    const ib = idx.has(b.id) ? idx.get(b.id)! : 999;
    return ia !== ib ? ia - ib : a.id.localeCompare(b.id);
  });
}

/**
 * 派生概览结论条。讲「弱曝光 · M/ok 平台提及你，X 已首推。补上 …的露出即可
 * 冲上强曝光。」缺数据时降级（未跑/全失败时给中性提示）。
 */
function deriveConclusion(
  metric: KeywordMetric | null,
  platforms: PlatformVM[],
): string {
  if (!metric || metric.total === 0) {
    return "该关键词还没有运行数据 · 运行一次采集后这里会给出曝光诊断与补位建议。";
  }
  const band = bandLabel(metric.status_band);
  const okCells = platforms.filter((p) => !isFailed(p));
  const firstPlats = okCells.filter((p) => p.mentioned && p.rank === 1).map((p) => p.name);
  const missingPlats = okCells.filter((p) => !p.mentioned).map((p) => p.name);
  const head = `${band} · ${metric.mentioned}/${metric.ok_total} 平台提及你`;
  const firstPart = firstPlats.length
    ? `，${firstPlats.slice(0, 2).join("、")} 已首推`
    : "，尚无平台把你列为首推";
  let tail = "。";
  if (metric.status_band !== "strong" && missingPlats.length) {
    tail = `。补上 ${missingPlats.slice(0, 3).join("、")} 的露出即可冲上强曝光。`;
  } else if (metric.status_band === "strong") {
    tail = "。继续保持，巩固高权重信源即可稳住强曝光。";
  } else {
    tail = "。";
  }
  return `${head}${firstPart}${tail}`;
}

/**
 * 拉取并装配某 (taskId, keyword) 的详情。返回响应式 detail + loading + error +
 * reload()。taskId/keyword 任一变化自动重拉。父组件在 SSE finished 时调
 * reload() 即可热刷新。
 */
export function useGeoKeywordDetail(
  taskId: Ref<number | null>,
  keyword: Ref<string | null>,
  brandTerms: Ref<string[]>,
) {
  const sidecar = useSidecar();

  const detail = ref<KeywordDetail | null>(null);
  const loading = ref(false);
  const error = ref(false);

  async function reload(): Promise<void> {
    const tid = taskId.value;
    const kw = keyword.value;
    if (tid == null || !kw) {
      detail.value = null;
      return;
    }
    loading.value = true;
    error.value = false;
    try {
      const [cellsRes, resultsRes, citRes] = await Promise.all([
        sidecar.client.get(`/api/monitor/geo/${tid}/latest-cells`),
        sidecar.client.get("/api/monitor/results", {
          params: { task_id: tid, limit: 8 },
        }),
        sidecar.client.get(`/api/monitor/geo/${tid}/citations`, {
          params: { days: 30, keyword: kw },
        }),
      ]);

      // 别名 race guard：await 期间用户切了关键词/任务 → 丢弃这次结果。
      if (taskId.value !== tid || keyword.value !== kw) return;

      const terms = brandTerms.value.filter(Boolean);

      // PLATFORMS：latest-cells 过滤到该关键词。
      const rawCells = (cellsRes.data?.cells ?? []) as RawCell[];
      const platforms = orderPlatforms(
        rawCells.filter((c) => c.keyword === kw).map((c) => cellToPlatform(c, terms)),
      );

      // results（DESC）→ METRIC（最新）+ HISTORY（正序）。
      const results = (resultsRes.data?.results ?? []) as Array<{
        checked_at: string | null;
        status: string;
        metric: { by_keyword?: Record<string, KeywordMetric> } | null;
      }>;
      const byKw = (r: { metric: { by_keyword?: Record<string, KeywordMetric> } | null }) =>
        r.metric?.by_keyword?.[kw] ?? null;
      const metric = results.length ? byKw(results[0]) : null;
      const lastRunIso = results.length ? results[0].checked_at : null;
      const history: HistoryPoint[] = [...results]
        .reverse() // DESC → 正序（旧→新）
        .map((r) => {
          const m = byKw(r);
          return {
            date: fmtShortDate(r.checked_at),
            soc: m?.soc ?? 0,
            first: m?.first_rank_rate ?? 0,
          };
        });

      // BOARD：citation leaderboard（已按关键词过滤）→ {domain,type,count,platforms数}。
      const lb = (citRes.data?.leaderboard ?? []) as Array<{
        domain: string;
        source_type: string;
        count: number;
        platforms: string[];
      }>;
      const board: BoardRow[] = lb.map((r) => ({
        domain: r.domain,
        type: r.source_type,
        count: r.count,
        platforms: Array.isArray(r.platforms) ? r.platforms.length : 0,
      }));

      const competitors = deriveCompetitors(platforms);
      const headCompetitor = competitors.length ? competitors[0].name : "";
      const topSource = board.length ? board[0].domain : "";
      const conclusion = deriveConclusion(metric, platforms);

      detail.value = {
        platforms,
        metric,
        history,
        competitors,
        board,
        lastRunIso,
        conclusion,
        headCompetitor,
        topSource,
      };
    } catch {
      if (taskId.value === tid && keyword.value === kw) {
        error.value = true;
        detail.value = null;
      }
    } finally {
      if (taskId.value === tid && keyword.value === kw) loading.value = false;
    }
  }

  // 选中关键词 / 任务变化 → 自动重拉。
  watch([taskId, keyword], () => void reload(), { immediate: true });

  // 平台引用率分母 = 该次运行的去重平台数（metric.total 优先；回退 cells 平台数）。
  const platformDenominator = computed<number>(() => {
    const d = detail.value;
    if (!d) return 0;
    if (d.metric && d.metric.total > 0) return d.metric.total;
    return d.platforms.length;
  });

  return { detail, loading, error, reload, platformDenominator };
}
