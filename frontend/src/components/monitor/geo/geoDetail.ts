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
  failReason?: string; // 失败原因分类(后端 geo.fail_reason;非失败 cell 为空)
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
  sentiment?: number; // 顶层 sentiment_score（数据中心聚合填；详情/趋势可忽略）
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
  weight: number;
}

/** GEO 分析页顶层聚合指标（result.metric 顶层，见 csm_core geo metrics.aggregate）。 */
export interface GeoTopMetric {
  soc: number;
  sentiment_score: number;
  mentioned: number;
  ok_total: number;
  total: number;
  status_band?: string;
  first_rank_rate?: number;
  // 完整度(§4.7):本次基于 measured/expected 个平台的数据。可选(旧数据无)。
  platforms_expected?: number;
  platforms_measured?: number;
  completeness?: number;
}
/** 覆盖榜单行（数据中心覆盖榜表派生）。 */
export interface GeoKeywordRow {
  keyword: string;
  cells: (PlatformVM | null)[]; // 与 platformIds 对齐
  mentioned: number; // 命中平台数
  total: number; // 平台总数
  band: CoverageBand;
  score: number; // 曝光分 0–100
  scoreDelta: number; // 环比（近 7 天，0 = 无基线/持平）
}

/** 待优化关键词行（重点视图）。 */
export interface GeoImproveRow {
  keyword: string;
  band: CoverageBand; // blind / partial
  missing: string[]; // 缺失平台 id（保持 platformIds 顺序）
}

/** GEO 数据中心分析（一个任务/品牌的跨关键词聚合）。 */
export interface GeoAnalytics {
  keywords: string[];                                  // 矩阵行
  platformIds: string[];                               // 矩阵列（平台 id，orderPlatforms 后去重）
  matrix: Record<string, Record<string, PlatformVM>>;  // matrix[keyword][platformId] = cell VM
  metric: GeoTopMetric | null;
  history: HistoryPoint[];
  board: BoardRow[];                                   // 全关键词带权重信源榜（后端已按 weight 排）
  lastRunIso: string | null;
  // ── 重构新增（对齐图二/三）──
  coverage: CoverageDist;               // 覆盖分布（霸屏/部分/盲区）
  socDelta: number;                     // 平均曝光率近 7 天环比
  sentimentDelta: number;               // 平均情感近 7 天环比
  keywordRows: GeoKeywordRow[];         // 覆盖榜（按曝光分降序）
  toImprove: GeoImproveRow[];           // 待优化（盲区优先）
  platformWeekly: PlatformWeeklySeries; // 各平台近 5 周覆盖率
}

// ── helper（移植 geo-shared.jsx）─────────────────────────────────────────
export function pct(v: number | undefined | null): string {
  return typeof v !== "number" || Number.isNaN(v) ? "—" : `${Math.round(v * 100)}%`;
}
/** 数值中位(升序取中;偶数取两中均值)。空数组返回 null。用于 7 天滚动中位稳定线。 */
export function median(nums: number[]): number | null {
  const xs = nums.filter((n) => typeof n === "number" && !Number.isNaN(n)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
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
/**
 * 占位平台标记 —— 该平台已配置但本次运行没有对应 cell（未跑 / 上次运行缺该
 * 平台）。占位卡渲染成中性灰「未运行」，不参与 metric / 竞品 / 散点派生。
 */
export const PENDING_STATUS = "pending";
export function isPending(p: { status: string }): boolean {
  return p.status === PENDING_STATUS;
}

export interface CellBadge {
  kind: "first" | "hit" | "miss" | "fail" | "pending";
  label: string;
  short: string;
  color: string;
}
/** 平台单格状态徽章（移植 geo-shared.jsx cellStatus）。 */
export function cellStatus(p: PlatformVM): CellBadge {
  if (isPending(p)) return { kind: "pending", label: "未运行", short: "未运行", color: "var(--ink-3)" };
  if (isFailed(p)) return { kind: "fail", label: "采集失败", short: "⚠ 失败", color: "var(--red)" };
  if (!p.mentioned) return { kind: "miss", label: "未提及", short: "✗ 未提及", color: "var(--red)" };
  if (p.rank === 1) return { kind: "first", label: "首推 #1", short: "★ #1", color: "var(--green)" };
  return { kind: "hit", label: `提及 #${p.rank}`, short: `#${p.rank}`, color: "var(--primary-deep)" };
}

/**
 * 失败原因 code → 人话 + 行动提示(替掉写死的「够不到平台」)。
 * 与后端 csm_core/monitor/geo/fail_reason.py 的 FailReason 枚举对齐。
 * 空 / unknown / 未知 code 回退旧文案「够不到平台」,保证永不显示裸 code。
 */
const FAIL_REASON_TEXT: Record<string, string> = {
  not_logged_in: "未登录 · 去设置登录",
  timeout: "响应超时 · 可重试",
  selector_drift: "页面改版 · 采集异常",
  rate_limited: "被限流 · 稍后重试",
  quota_exhausted: "配额/余额不足 · 查账户",
  content_blocked: "内容被拦 · 换个说法",
  network: "网络/浏览器异常 · 重试",
  interrupted: "已中断 · 重跑一次",
};
export function failReasonLabel(code: string | undefined | null): string {
  return FAIL_REASON_TEXT[(code || "").trim()] ?? "够不到平台";
}

/** 已配置但本次无 cell 的平台占位 VM（中性灰「未运行」卡用）。 */
export function placeholderPlatform(id: string): PlatformVM {
  return {
    id,
    name: platformLabel(id),
    status: PENDING_STATUS,
    mentioned: false,
    rank: -1,
    sentiment: "na",
    citations: 0,
    summary: "",
    answer: "",
    excerpt: "",
    recommended: [],
    cites: [],
  };
}

// ── 数据中心 GEO 覆盖派生（覆盖榜 / 概览覆盖分布 / 待优化 / 曝光分）────────
// 纯函数，单测见 __tests__/geoDetail.spec.ts。「覆盖/提及」= cellStatus 命中
// first|hit；未提及/失败/未跑/缺格都算「未覆盖」。

export type CoverageBand = "dominated" | "partial" | "blind";

export interface KeywordCoverage {
  mentioned: number; // 提及（首推或上榜）你的平台数
  total: number; // 比较的平台总数（= platformIds.length）
  band: CoverageBand; // dominated 霸屏 · partial 部分覆盖 · blind 盲区
  missing: string[]; // 未覆盖平台 id（保持 platformIds 顺序）
}

/** 单关键词跨平台覆盖分类。 */
export function classifyKeywordCoverage(
  row: Record<string, PlatformVM> | undefined,
  platformIds: string[],
): KeywordCoverage {
  let mentioned = 0;
  const missing: string[] = [];
  for (const p of platformIds) {
    const cell = row?.[p];
    const kind = cell ? cellStatus(cell).kind : "miss";
    if (kind === "first" || kind === "hit") mentioned += 1;
    else missing.push(p);
  }
  const total = platformIds.length;
  const band: CoverageBand =
    mentioned === 0 ? "blind" : mentioned === total ? "dominated" : "partial";
  return { mentioned, total, band, missing };
}

export interface CoverageDist {
  dominated: number;
  partial: number;
  blind: number;
}

/** 跨关键词汇总覆盖分布（概览条 stacked bar）。 */
export function coverageDistribution(
  matrix: Record<string, Record<string, PlatformVM>>,
  keywords: string[],
  platformIds: string[],
): CoverageDist {
  const dist: CoverageDist = { dominated: 0, partial: 0, blind: 0 };
  for (const kw of keywords) {
    dist[classifyKeywordCoverage(matrix[kw], platformIds).band] += 1;
  }
  return dist;
}

/** 曝光分 0–100：有 soc 用 round(soc×100)，否则回退覆盖率 mentioned/total。 */
export function exposureScore(
  soc: number | null | undefined,
  coverage?: { mentioned: number; total: number },
): number {
  const clamp = (v: number) => Math.max(0, Math.min(100, Math.round(v)));
  if (typeof soc === "number" && !Number.isNaN(soc)) return clamp(soc * 100);
  if (coverage && coverage.total > 0) return clamp((coverage.mentioned / coverage.total) * 100);
  return 0;
}

export interface PlatformWeeklySeries {
  weekLabels: string[];
  series: { platformId: string; rates: (number | null)[] }[];
}

const _WEEK_MS = 7 * 86_400_000;
/** 某日期所在自然周的周一 0 点（本地时区）时间戳。 */
function _startOfWeekMs(d: Date): number {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (x.getDay() + 6) % 7; // 周一=0 … 周日=6
  x.setDate(x.getDate() - dow);
  return x.getTime();
}

/**
 * 逐平台近 `weeks` 周覆盖率（mentioned/ok_total×100）。每个 (平台,周) 取该周
 * 最新一次运行；空周 null。标签从旧到新，末位 = 本周。
 */
export function weeklyPlatformCoverage(
  results: Array<{
    checked_at: string | null;
    metric: { by_platform?: Record<string, { mentioned: number; ok_total: number }> } | null;
  }>,
  platformIds: string[],
  now: Date,
  weeks = 5,
): PlatformWeeklySeries {
  const nowWeek = _startOfWeekMs(now);
  const latestTs: Record<string, number[]> = {};
  const rates: Record<string, (number | null)[]> = {};
  for (const p of platformIds) {
    latestTs[p] = Array(weeks).fill(-Infinity);
    rates[p] = Array(weeks).fill(null);
  }
  for (const r of results) {
    if (!r.checked_at) continue;
    const t = new Date(r.checked_at);
    if (Number.isNaN(t.getTime())) continue;
    const weeksAgo = Math.round((nowWeek - _startOfWeekMs(t)) / _WEEK_MS);
    if (weeksAgo < 0 || weeksAgo >= weeks) continue;
    const idx = weeks - 1 - weeksAgo;
    const ts = t.getTime();
    const bp = r.metric?.by_platform ?? {};
    for (const p of platformIds) {
      const cell = bp[p];
      if (!cell || !cell.ok_total) continue;
      if (ts >= latestTs[p][idx]) {
        latestTs[p][idx] = ts;
        rates[p][idx] = Math.round((cell.mentioned / cell.ok_total) * 100);
      }
    }
  }
  const weekLabels: string[] = [];
  for (let i = 0; i < weeks; i++) weekLabels.push(i === weeks - 1 ? "本周" : `W${i + 1}`);
  return { weekLabels, series: platformIds.map((p) => ({ platformId: p, rates: rates[p] })) };
}

/**
 * 信源榜上榜门槛：引用次数 ≥ `minCount`（默认 10）且有真实网址 —— 域名非空、
 * 含「.」（剔除空域名与「其他来源」这类聚合桶，它们没有可点开的网址）。
 */
export function filterBoard(rows: BoardRow[], minCount = 10): BoardRow[] {
  return rows.filter((r) => r.count >= minCount && /\./.test((r.domain || "").trim()));
}

/**
 * 合并「已配置平台」与「本次真实采集 cell」：每个配置平台若有 cell 用真卡，
 * 否则补占位卡。保证概览/平台对比/热力矩阵恒展示全部已配置平台（未跑也占位）。
 * 真实 cell 命中但不在配置里的平台也保留（追加在尾部），避免漏显。
 */
export function mergeConfiguredPlatforms(
  cells: PlatformVM[],
  configured: string[],
): PlatformVM[] {
  const byId = new Map(cells.map((c) => [c.id, c]));
  const seen = new Set<string>();
  const out: PlatformVM[] = [];
  for (const id of configured) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(byId.get(id) ?? placeholderPlatform(id));
  }
  // 配置之外但确有 cell 的平台（理论少见）兜底显示。
  for (const c of cells) {
    if (!seen.has(c.id)) {
      seen.add(c.id);
      out.push(c);
    }
  }
  return out;
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
  fail_reason?: string;
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
    failReason: c.fail_reason || "",
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
  /** 本次真实采集到的平台 cell（metric / 竞品 / 散点 / 结论派生只用这个）。 */
  platforms: PlatformVM[];
  /**
   * 展示用平台列表 = 已配置平台并入真实 cell，缺 cell 的配置平台补占位。
   * 概览各平台卡 / 平台对比卡片 / 热力矩阵列恒展示全部已配置平台。
   */
  displayPlatforms: PlatformVM[];
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
function dedupeById(vms: PlatformVM[]): PlatformVM[] {
  const seen = new Set<string>();
  const out: PlatformVM[] = [];
  for (const v of vms) {
    if (!seen.has(v.id)) {
      seen.add(v.id);
      out.push(v);
    }
  }
  return out;
}
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
  /** 该任务已配置的平台（config.platforms）——用来补占位卡。可空。 */
  configuredPlatforms?: Ref<string[]>,
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
      // 趋势横轴 = 最近 7 天（按天聚合，每天取当天最后一次运行的指标），日期标 M/D。
      // results 是 DESC（新→旧），同一天第一次遇到的即当天最后一跑。
      const DAY_MS = 86_400_000;
      const cutoff = Date.now() - 7 * DAY_MS;
      const seenDay = new Map<string, { iso: string; p: HistoryPoint }>();
      for (const r of results) {
        if (!r.checked_at) continue;
        const t = new Date(r.checked_at).getTime();
        if (isNaN(t) || t < cutoff) continue;
        const date = fmtShortDate(r.checked_at);
        if (seenDay.has(date)) continue; // DESC: first seen = latest run that day
        const m = byKw(r);
        seenDay.set(date, { iso: r.checked_at, p: { date, soc: m?.soc ?? 0, first: m?.first_rank_rate ?? 0 } });
      }
      const history: HistoryPoint[] = [...seenDay.values()]
        .sort((a, b) => a.iso.localeCompare(b.iso)) // old → new
        .map((e) => e.p);

      // BOARD：citation leaderboard（已按关键词过滤）→ {domain,type,count,platforms数,weight}。
      const lb = (citRes.data?.leaderboard ?? []) as Array<{
        domain: string;
        source_type: string;
        count: number;
        platforms: string[];
        weight?: number;
      }>;
      // 上榜门槛：引用 ≥ 10 次 + 有真实网址（与数据中心 useGeoAnalytics 一致），
      // 否则信源图例会拖出几十个低频域名把散点图压得很小。
      const board: BoardRow[] = filterBoard(
        lb.map((r) => ({
          domain: r.domain,
          type: r.source_type,
          count: r.count,
          platforms: Array.isArray(r.platforms) ? r.platforms.length : 0,
          weight: r.weight ?? 0,
        })),
      );

      const competitors = deriveCompetitors(platforms);
      const headCompetitor = competitors.length ? competitors[0].name : "";
      const topSource = board.length ? board[0].domain : "";
      const conclusion = deriveConclusion(metric, platforms);

      // 展示用列表：已配置平台并入真实 cell（缺的补占位）。无配置时退化为真实
      // cell（保持旧行为）。占位卡不参与上面的 metric / 竞品 / 散点 / 结论派生。
      const configured = configuredPlatforms?.value ?? [];
      const displayPlatforms = configured.length
        ? orderPlatforms(mergeConfiguredPlatforms(platforms, configured))
        : platforms;

      detail.value = {
        platforms,
        displayPlatforms,
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

  // 选中关键词 / 任务 / 配置平台变化 → 自动重拉（配置平台变了占位卡也要变）。
  watch(
    [taskId, keyword, () => configuredPlatforms?.value],
    () => void reload(),
    { immediate: true },
  );

  // 平台引用率分母 = 该次运行的去重平台数（metric.total 优先；回退 cells 平台数）。
  const platformDenominator = computed<number>(() => {
    const d = detail.value;
    if (!d) return 0;
    if (d.metric && d.metric.total > 0) return d.metric.total;
    return d.platforms.length;
  });

  return { detail, loading, error, reload, platformDenominator };
}

/**
 * 拉取并装配某任务（一个品牌）的跨关键词 GEO 分析数据。
 * 与 useGeoKeywordDetail 的差异：
 *   - cells 不按关键词过滤 → 全关键词 matrix[keyword][platformId]
 *   - citations 不传 keyword → 全任务带权重信源榜
 *   - metric 取 result.metric 顶层（非 by_keyword）
 *   - history 读顶层 soc / first_rank_rate（无需 by_keyword 下钻）
 *   - 返回 analytics（GeoAnalytics）而非 detail（KeywordDetail）
 */
export function useGeoAnalytics(
  taskId: Ref<number | null>,
  brandTerms: Ref<string[]>,
  configuredKeywords: Ref<string[]>,   // task.config.keywords（行顺序优先）
  configuredPlatforms: Ref<string[]>,  // task.config.platforms（列顺序参考）
) {
  const sidecar = useSidecar();
  const analytics = ref<GeoAnalytics | null>(null);
  const loading = ref(false);
  const error = ref(false);

  async function reload(): Promise<void> {
    const tid = taskId.value;
    if (tid == null) {
      analytics.value = null;
      return;
    }
    loading.value = true;
    error.value = false;
    try {
      const [cellsRes, resultsRes, citRes] = await Promise.all([
        sidecar.client.get(`/api/monitor/geo/${tid}/latest-cells`),
        sidecar.client.get("/api/monitor/results", {
          // 60 条够近 5 周（GEO 多为日级或更稀）做逐平台周分桶 + 近 7 天首末环比。
          params: { task_id: tid, limit: 60 },
        }),
        sidecar.client.get(`/api/monitor/geo/${tid}/citations`, {
          params: { days: 30 },
        }),
      ]);

      // race guard：await 期间用户切换了任务 → 丢弃结果。
      if (taskId.value !== tid) return;

      const terms = brandTerms.value.filter(Boolean);

      // MATRIX：全量 cells（不按关键词过滤），按 keyword × platformId 分组。
      const rawCells = (cellsRes.data?.cells ?? []) as RawCell[];
      const matrix: Record<string, Record<string, PlatformVM>> = {};
      const allVMs: PlatformVM[] = [];
      for (const c of rawCells) {
        const vm = cellToPlatform(c, terms);
        (matrix[c.keyword] ||= {})[vm.id] = vm;
        allVMs.push(vm);
      }
      const livePlatforms = dedupeById(allVMs);
      const cfgPlatforms = configuredPlatforms.value.filter(Boolean);
      const displayPlatforms = cfgPlatforms.length
        ? orderPlatforms(mergeConfiguredPlatforms(livePlatforms, cfgPlatforms))
        : orderPlatforms(livePlatforms);
      const platformIds = displayPlatforms.map((p) => p.id);

      // keywords：config.keywords 保序（含未跑到的），回退 cells 里出现的。
      const cellKeywords = Object.keys(matrix);
      const ckws = configuredKeywords.value.filter(Boolean);
      const keywords = ckws.length ? ckws : cellKeywords;

      // METRIC + HISTORY：results DESC → metric 取顶层 + by_keyword/by_platform 下钻。
      type FullMetric = GeoTopMetric & {
        by_keyword?: Record<string, KeywordMetric>;
        by_platform?: Record<string, { mentioned: number; ok_total: number }>;
      };
      const results = (resultsRes.data?.results ?? []) as Array<{
        checked_at: string | null;
        status: string;
        metric: FullMetric | null;
      }>;
      const metric: GeoTopMetric | null = results.length
        ? (results[0].metric ?? null)
        : null;
      const lastRunIso: string | null = results.length ? (results[0].checked_at ?? null) : null;

      // 趋势横轴：最近 7 天按天聚合（DESC 先遇到 = 当天最后一跑），整条 metric 入桶
      // 以便派生 soc/first/sentiment 趋势 + 首末环比 + 逐词曝光分基线。
      const DAY_MS = 86_400_000;
      const cutoff = Date.now() - 7 * DAY_MS;
      const seenDay = new Map<string, { iso: string; metric: FullMetric | null }>();
      for (const r of results) {
        if (!r.checked_at) continue;
        const t = new Date(r.checked_at).getTime();
        if (isNaN(t) || t < cutoff) continue;
        const date = fmtShortDate(r.checked_at);
        if (seenDay.has(date)) continue;
        seenDay.set(date, { iso: r.checked_at, metric: r.metric });
      }
      const days = [...seenDay.values()].sort((a, b) => a.iso.localeCompare(b.iso)); // old → new
      const history: HistoryPoint[] = days.map((d) => ({
        date: fmtShortDate(d.iso),
        soc: d.metric?.soc ?? 0,
        first: d.metric?.first_rank_rate ?? 0,
        sentiment: d.metric?.sentiment_score ?? 0,
      }));
      // 首末环比（近 7 天窗口内最旧日 → 最新日）。
      const socDelta = history.length >= 2 ? history[history.length - 1].soc - history[0].soc : 0;
      const sentimentDelta =
        history.length >= 2
          ? (history[history.length - 1].sentiment ?? 0) - (history[0].sentiment ?? 0)
          : 0;

      // BOARD：全任务 citation leaderboard（无 keyword 过滤），带 weight。
      // 上榜门槛：引用 ≥ 10 次 + 有真实网址（filterBoard）。
      const lb = (citRes.data?.leaderboard ?? []) as Array<{
        domain: string;
        source_type: string;
        count: number;
        platforms: string[];
        weight?: number;
      }>;
      const board: BoardRow[] = filterBoard(
        lb.map((r) => ({
          domain: r.domain,
          type: r.source_type,
          count: r.count,
          platforms: Array.isArray(r.platforms) ? r.platforms.length : 0,
          weight: r.weight ?? 0,
        })),
      );

      // ── 覆盖派生（图二/三）──
      const coverage = coverageDistribution(matrix, keywords, platformIds);
      const platformWeekly = weeklyPlatformCoverage(results, platformIds, new Date(), 5);
      const latestByKw = (metric as FullMetric | null)?.by_keyword ?? {};
      const baseByKw = (days.length ? days[0].metric?.by_keyword : null) ?? {};
      const keywordRows: GeoKeywordRow[] = keywords
        .map((kw) => {
          const cov = classifyKeywordCoverage(matrix[kw], platformIds);
          const cells = platformIds.map((p) => matrix[kw]?.[p] ?? null);
          const score = exposureScore(latestByKw[kw]?.soc, {
            mentioned: cov.mentioned,
            total: cov.total,
          });
          const baseSoc = baseByKw[kw]?.soc;
          const scoreDelta = typeof baseSoc === "number" ? score - exposureScore(baseSoc) : 0;
          return {
            keyword: kw,
            cells,
            mentioned: cov.mentioned,
            total: cov.total,
            band: cov.band,
            score,
            scoreDelta,
          };
        })
        .sort((a, b) => b.score - a.score || b.mentioned - a.mentioned);
      const bandWeight: Record<CoverageBand, number> = { blind: 0, partial: 1, dominated: 2 };
      const toImprove: GeoImproveRow[] = keywords
        .map((kw) => {
          const cov = classifyKeywordCoverage(matrix[kw], platformIds);
          return { keyword: kw, band: cov.band, missing: cov.missing, _m: cov.mentioned };
        })
        .filter((r) => r.band !== "dominated")
        .sort((a, b) => bandWeight[a.band] - bandWeight[b.band] || a._m - b._m)
        .map(({ keyword, band, missing }) => ({ keyword, band, missing }));

      if (taskId.value !== tid) return;
      analytics.value = {
        keywords,
        platformIds,
        matrix,
        metric,
        history,
        board,
        lastRunIso,
        coverage,
        socDelta,
        sentimentDelta,
        keywordRows,
        toImprove,
        platformWeekly,
      };
    } catch {
      if (taskId.value === tid) {
        error.value = true;
        analytics.value = null;
      }
    } finally {
      if (taskId.value === tid) loading.value = false;
    }
  }

  watch(
    [taskId, brandTerms, configuredKeywords, configuredPlatforms],
    () => void reload(),
    { immediate: true },
  );

  return { analytics, loading, error, reload };
}
