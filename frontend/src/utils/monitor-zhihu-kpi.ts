/**
 * 知乎监测「批次汇总」聚合 KPI —— 由各问题最新快照聚合，无需后端字段。
 *   - hitQuestions: matched_count > 0 的问题数（命中问题数 X/Y 的 X）
 *   - total:        问题总数（Y）
 *   - avgRank:      已进榜问题（rank > 0）的平均最高排名，保留 1 位小数；无则 null
 *   - ownHits:      所有问题 matched_count 之和（自家命中数）
 */
export interface ZhihuKpiInput {
  matched_count: number;
  rank: number;
}
export interface ZhihuBatchKpis {
  total: number;
  hitQuestions: number;
  avgRank: number | null;
  ownHits: number;
}

export function batchZhihuKpis(snapshots: ZhihuKpiInput[]): ZhihuBatchKpis {
  const total = snapshots.length;
  let hitQuestions = 0;
  let ownHits = 0;
  const ranked: number[] = [];
  for (const s of snapshots) {
    if (s.matched_count > 0) hitQuestions++;
    ownHits += s.matched_count;
    if (s.rank > 0) ranked.push(s.rank);
  }
  const avgRank =
    ranked.length > 0
      ? Math.round((ranked.reduce((a, b) => a + b, 0) / ranked.length) * 10) / 10
      : null;
  return { total, hitQuestions, avgRank, ownHits };
}

/**
 * 知乎搜索「任务汇总」聚合 KPI —— 由该任务各关键词最新结果聚合。
 *   - hitKeywords:   matched_count > 0 的关键词数（命中关键词数）
 *   - total:         关键词总数
 *   - bestFirstRank: 命中关键词中最好的首位（min first_rank, first_rank>0）；无则 null
 *   - ownHits:       所有关键词 matched_count 之和（自家命中数）
 */
export interface ZhihuSearchKpiInput {
  matched_count: number;
  first_rank: number;
}
export interface ZhihuSearchKpis {
  total: number;
  hitKeywords: number;
  bestFirstRank: number | null;
  ownHits: number;
}

export function batchZhihuSearchKpis(keywords: ZhihuSearchKpiInput[]): ZhihuSearchKpis {
  const total = keywords.length;
  let hitKeywords = 0;
  let ownHits = 0;
  const firsts: number[] = [];
  for (const k of keywords) {
    if (k.matched_count > 0) hitKeywords++;
    ownHits += k.matched_count;
    if (k.first_rank > 0) firsts.push(k.first_rank);
  }
  const bestFirstRank = firsts.length > 0 ? Math.min(...firsts) : null;
  return { total, hitKeywords, bestFirstRank, ownHits };
}
