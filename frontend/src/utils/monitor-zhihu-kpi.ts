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
