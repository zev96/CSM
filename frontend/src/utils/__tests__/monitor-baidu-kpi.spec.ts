import { describe, it, expect } from "vitest";
import { batchBaiduKpis } from "../monitor-zhihu-kpi";

const kw = (default_matched_count: number, default_first_rank: number, news_matched_count = 0) =>
  ({ default_matched_count, default_first_rank, news_matched_count });

describe("batchBaiduKpis", () => {
  it("counts hit keywords (default OR news matched > 0) over total", () => {
    const k = batchBaiduKpis([kw(2, 3), kw(0, 0, 1), kw(0, 0, 0)]);
    expect(k.total).toBe(3);
    expect(k.hitKeywords).toBe(2);
  });
  it("bestDefaultRank = MIN default_first_rank among >0", () => {
    expect(batchBaiduKpis([kw(1, 5), kw(1, 2), kw(0, 0)]).bestDefaultRank).toBe(2);
  });
  it("bestDefaultRank null when none ranked", () => {
    expect(batchBaiduKpis([kw(0, 0), kw(0, 0, 2)]).bestDefaultRank).toBeNull();
  });
  it("ownHits sums default + news matched", () => {
    expect(batchBaiduKpis([kw(2, 1, 1), kw(3, 2, 0)]).ownHits).toBe(6);
  });
  it("handles empty", () => {
    expect(batchBaiduKpis([])).toEqual({ total: 0, hitKeywords: 0, bestDefaultRank: null, ownHits: 0 });
  });
});
