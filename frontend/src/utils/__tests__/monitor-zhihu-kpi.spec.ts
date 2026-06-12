import { describe, it, expect } from "vitest";
import { batchZhihuKpis } from "../monitor-zhihu-kpi";

const snap = (matched_count: number, rank: number) => ({ matched_count, rank });

describe("batchZhihuKpis", () => {
  it("counts hit questions (matched_count > 0) over total", () => {
    const k = batchZhihuKpis([snap(2, 3), snap(0, -1), snap(1, 5)]);
    expect(k.total).toBe(3);
    expect(k.hitQuestions).toBe(2);
  });
  it("averages rank over ranked questions only (excludes rank<=0)", () => {
    const k = batchZhihuKpis([snap(1, 4), snap(1, 6), snap(0, -1)]);
    expect(k.avgRank).toBe(5);
  });
  it("avgRank is null when nothing is ranked", () => {
    const k = batchZhihuKpis([snap(0, -1), snap(0, -1)]);
    expect(k.avgRank).toBeNull();
  });
  it("sums own-brand hits (total matched_count)", () => {
    const k = batchZhihuKpis([snap(2, 3), snap(0, -1), snap(3, 1)]);
    expect(k.ownHits).toBe(5);
  });
  it("handles empty input", () => {
    expect(batchZhihuKpis([])).toEqual({ total: 0, hitQuestions: 0, avgRank: null, ownHits: 0 });
  });
});
