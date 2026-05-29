/**
 * Monitor task snapshot shaping — single source of truth for converting
 * the backend's MonitorResult row into the shape the UI renders.
 *
 * Lives in utils/ so MonitorView and the per-tab sub-modules (comment /
 * tasks / alerts) all consume the same shaping. Before this lived inline
 * in MonitorView.vue around line 342; pulling it out is the first step
 * of the v0.5.2-audit MonitorView split (Phase 1).
 *
 * Backwards-compat note: the function tolerates the **old** Zhihu schema
 * (``metric.top_n``, no ``matched_count``, ``rank > 0`` ⇒ matched=1) and
 * the **new** comment schema (``metric.matched_count`` / ``matched_ranks``
 * / ``scope_total`` / ``hot_comments`` array). Bumping a single schema
 * shouldn't ripple to every UI site.
 */

export interface TaskSnapshot {
  matched: boolean;
  rank: number;
  /** 评论：用户填的"理想排名上限"。知乎：用户填的 top_n（前几条答案要扫描） */
  alert_top_n: number;
  /** 评论后台实际扫描范围（默认 150）。rank=-1 时区分"丢失"vs"无" */
  scrape_top_n: number;
  /** 评论：本次实际比对了多少条 hot 评论；知乎不用 */
  scope_total: number;
  hot_comments: Array<{ author?: string; text?: string; rank?: number; nickname?: string }>;
  total_fetched: number;
  my_comment_text: string;
  checked_at: string;
  status: string;
  /** 知乎专用：前 top_n 条答案里命中目标品牌的条数 */
  matched_count: number;
  /** 知乎专用：所有命中位置（1-based） */
  matched_ranks: number[];
  /** 知乎专用：用户的目标品牌关键词（详情卡 / 抢占者高亮要用） */
  target_brand: string;
  /** 知乎专用：问题浏览量（被浏览数）；缺失为 null */
  question_visit_count: number | null;
}

export interface TaskSnapshotPair {
  latest: TaskSnapshot | null;
  prev: TaskSnapshot | null;
}

export function resultToSnapshot(r: any): TaskSnapshot | null {
  if (!r) return null;
  const m = r.metric ?? {};
  // alert_top_n 优先 metric.alert_top_n（评论新后端）/ metric.top_n（知乎 +
  // 旧评论 result）；再缺给个 5 兜底
  const alertTopN =
    typeof m.alert_top_n === "number" ? m.alert_top_n
    : typeof m.top_n === "number" ? m.top_n
    : 5;
  const scrapeTopN = typeof m.scrape_top_n === "number" ? m.scrape_top_n : 150;
  const scopeTotal =
    typeof m.scope_total === "number" ? m.scope_total
    : Array.isArray(m.hot_comments) ? m.hot_comments.length
    : 0;
  // matched_count / matched_ranks：知乎新后端字段；旧 result（无 matched_count）
  // 用 rank > 0 兜底成 1，rank=-1 兜底成 0（单命中假设，避免 NaN）。
  const rankVal = typeof r.rank === "number" ? r.rank : -1;
  const matchedCount =
    typeof m.matched_count === "number" ? m.matched_count
    : rankVal > 0 ? 1 : 0;
  const matchedRanks =
    Array.isArray(m.matched_ranks) ? m.matched_ranks.filter((x: any) => typeof x === "number")
    : rankVal > 0 ? [rankVal] : [];
  return {
    matched: Boolean(m.matched) || matchedCount > 0,
    rank: rankVal,
    alert_top_n: alertTopN,
    scrape_top_n: scrapeTopN,
    scope_total: scopeTotal,
    hot_comments: Array.isArray(m.hot_comments) ? m.hot_comments : [],
    total_fetched: typeof m.total_fetched === "number" ? m.total_fetched : 0,
    my_comment_text: typeof m.my_comment_text === "string" ? m.my_comment_text : "",
    checked_at: r.checked_at ?? "",
    status: r.status ?? "",
    matched_count: matchedCount,
    matched_ranks: matchedRanks,
    target_brand: typeof m.target_brand === "string" ? m.target_brand : "",
    question_visit_count:
      typeof m.question_visit_count === "number" ? m.question_visit_count : null,
  };
}
