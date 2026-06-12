import { describe, it, expect } from "vitest";
import { batchZhihuSearchKpis } from "../monitor-zhihu-kpi";

const kw = (matched_count: number, first_rank: number) => ({ matched_count, first_rank });

describe("batchZhihuSearchKpis", () => {
  it("counts hit keywords (matched_count > 0) over total", () => {
    const k = batchZhihuSearchKpis([kw(2, 3), kw(0, 0), kw(1, 5)]);
    expect(k.total).toBe(3);
    expect(k.hitKeywords).toBe(2);
  });
  it("bestFirstRank is the MIN first_rank among hits (first_rank > 0)", () => {
    const k = batchZhihuSearchKpis([kw(1, 5), kw(1, 2), kw(0, 0)]);
    expect(k.bestFirstRank).toBe(2);
  });
  it("bestFirstRank is null when nothing ranked", () => {
    const k = batchZhihuSearchKpis([kw(0, 0), kw(0, 0)]);
    expect(k.bestFirstRank).toBeNull();
  });
  it("sums own-brand hits (total matched_count)", () => {
    const k = batchZhihuSearchKpis([kw(2, 3), kw(3, 1)]);
    expect(k.ownHits).toBe(5);
  });
  it("handles empty input", () => {
    expect(batchZhihuSearchKpis([])).toEqual({ total: 0, hitKeywords: 0, bestFirstRank: null, ownHits: 0 });
  });
});
