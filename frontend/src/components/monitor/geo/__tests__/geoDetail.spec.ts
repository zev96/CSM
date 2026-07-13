import { describe, it, expect } from "vitest";

import {
  classifyKeywordCoverage,
  coverageDistribution,
  exposureScore,
  weeklyPlatformCoverage,
  filterBoard,
  placeholderPlatform,
  failReasonLabel,
  median,
  type PlatformVM,
  type BoardRow,
} from "@/components/monitor/geo/geoDetail";

// 极简 PlatformVM 工厂 —— 只设与 cellStatus 相关的字段。
function vm(id: string, opts: Partial<PlatformVM> = {}): PlatformVM {
  return {
    id,
    name: id,
    status: "ok",
    mentioned: false,
    rank: -1,
    sentiment: "na",
    citations: 0,
    summary: "",
    answer: "",
    excerpt: "",
    recommended: [],
    cites: [],
    ...opts,
  };
}
const first = (id: string) => vm(id, { mentioned: true, rank: 1 }); // 首推 #1
const hit = (id: string, rank = 3) => vm(id, { mentioned: true, rank }); // 提及 #rank
const miss = (id: string) => vm(id, { mentioned: false }); // 未提及
const fail = (id: string) => vm(id, { status: "error" }); // 采集失败

describe("classifyKeywordCoverage", () => {
  const PLATS = ["doubao", "tongyi", "kimi"];

  it("全部平台提及 → dominated，无缺失", () => {
    const row = { doubao: first("doubao"), tongyi: hit("tongyi"), kimi: hit("kimi") };
    const c = classifyKeywordCoverage(row, PLATS);
    expect(c.band).toBe("dominated");
    expect(c.mentioned).toBe(3);
    expect(c.total).toBe(3);
    expect(c.missing).toEqual([]);
  });

  it("无平台提及 → blind，缺失全部", () => {
    const row = { doubao: miss("doubao"), tongyi: miss("tongyi"), kimi: miss("kimi") };
    const c = classifyKeywordCoverage(row, PLATS);
    expect(c.band).toBe("blind");
    expect(c.mentioned).toBe(0);
    expect(c.missing).toEqual(["doubao", "tongyi", "kimi"]);
  });

  it("部分提及 → partial，缺失列出未覆盖平台", () => {
    const row = { doubao: first("doubao"), tongyi: miss("tongyi"), kimi: hit("kimi") };
    const c = classifyKeywordCoverage(row, PLATS);
    expect(c.band).toBe("partial");
    expect(c.mentioned).toBe(2);
    expect(c.missing).toEqual(["tongyi"]);
  });

  it("缺格（未跑该平台）与采集失败都算缺失，不算提及", () => {
    // doubao 提及；tongyi 失败；kimi 整列缺格（占位/未运行）
    const row = { doubao: hit("doubao"), tongyi: fail("tongyi"), kimi: placeholderPlatform("kimi") };
    const c = classifyKeywordCoverage(row, PLATS);
    expect(c.band).toBe("partial");
    expect(c.mentioned).toBe(1);
    expect(c.missing).toEqual(["tongyi", "kimi"]);
  });

  it("整行无数据（row undefined）→ blind，缺失全部", () => {
    const c = classifyKeywordCoverage(undefined, PLATS);
    expect(c.band).toBe("blind");
    expect(c.mentioned).toBe(0);
    expect(c.missing).toEqual(["doubao", "tongyi", "kimi"]);
  });
});

describe("coverageDistribution", () => {
  it("按关键词分类汇总 霸屏/部分/盲区", () => {
    const PLATS = ["doubao", "tongyi"];
    const matrix = {
      A: { doubao: first("doubao"), tongyi: hit("tongyi") }, // dominated
      B: { doubao: first("doubao"), tongyi: miss("tongyi") }, // partial
      C: { doubao: miss("doubao"), tongyi: miss("tongyi") }, // blind
      D: { doubao: hit("doubao"), tongyi: hit("tongyi") }, // dominated
    };
    const dist = coverageDistribution(matrix, ["A", "B", "C", "D"], PLATS);
    expect(dist).toEqual({ dominated: 2, partial: 1, blind: 1 });
  });

  it("空关键词列表 → 全 0", () => {
    expect(coverageDistribution({}, [], [])).toEqual({ dominated: 0, partial: 0, blind: 0 });
  });
});

describe("exposureScore", () => {
  it("有 soc → round(soc*100)", () => {
    expect(exposureScore(0.85)).toBe(85);
    expect(exposureScore(0.6)).toBe(60);
    expect(exposureScore(0.784)).toBe(78);
  });

  it("soc=0 是有效值 → 0（不回退覆盖率）", () => {
    expect(exposureScore(0, { mentioned: 3, total: 5 })).toBe(0);
  });

  it("无 soc → 回退用覆盖率 mentioned/total", () => {
    expect(exposureScore(null, { mentioned: 3, total: 5 })).toBe(60);
    expect(exposureScore(undefined, { mentioned: 5, total: 5 })).toBe(100);
  });

  it("既无 soc 也无覆盖率 → 0；越界值夹到 0–100", () => {
    expect(exposureScore(null)).toBe(0);
    expect(exposureScore(null, { mentioned: 0, total: 0 })).toBe(0);
    expect(exposureScore(1.5)).toBe(100);
  });
});

describe("weeklyPlatformCoverage", () => {
  // now = 2026-06-06（周六）；本周起始周一 = 2026-06-01。
  const NOW = new Date("2026-06-06T12:00:00");
  const PLATS = ["doubao", "tongyi"];

  function res(iso: string, byPlatform: Record<string, { mentioned: number; ok_total: number }>) {
    return { checked_at: iso, metric: { by_platform: byPlatform } };
  }

  it("逐平台按周分桶，覆盖率=mentioned/ok_total*100，空周为 null", () => {
    const results = [
      res("2026-06-06T09:00:00", { doubao: { mentioned: 4, ok_total: 5 } }), // 本周 → 80
      res("2026-05-27T09:00:00", { doubao: { mentioned: 2, ok_total: 5 } }), // W4(1周前) → 40
      res("2026-05-08T09:00:00", { doubao: { mentioned: 1, ok_total: 5 } }), // W1(4周前) → 20
    ];
    const out = weeklyPlatformCoverage(results, PLATS, NOW, 5);
    // 标签从旧到新，最后一个是本周
    expect(out.weekLabels).toEqual(["W1", "W2", "W3", "W4", "本周"]);
    const doubao = out.series.find((s) => s.platformId === "doubao")!;
    expect(doubao.rates).toEqual([20, null, null, 40, 80]);
    const tongyi = out.series.find((s) => s.platformId === "tongyi")!;
    expect(tongyi.rates).toEqual([null, null, null, null, null]);
  });

  it("同一周多次运行 → 取该周最新一次", () => {
    const results = [
      res("2026-06-02T09:00:00", { doubao: { mentioned: 5, ok_total: 5 } }), // 本周早一点 100
      res("2026-06-06T09:00:00", { doubao: { mentioned: 4, ok_total: 5 } }), // 本周最新 80（应胜出）
    ];
    const out = weeklyPlatformCoverage(results, PLATS, NOW, 5);
    const doubao = out.series.find((s) => s.platformId === "doubao")!;
    expect(doubao.rates[4]).toBe(80);
  });

  it("ok_total=0 视为该周无有效数据 → null", () => {
    const results = [res("2026-06-06T09:00:00", { doubao: { mentioned: 0, ok_total: 0 } })];
    const out = weeklyPlatformCoverage(results, PLATS, NOW, 5);
    const doubao = out.series.find((s) => s.platformId === "doubao")!;
    expect(doubao.rates[4]).toBeNull();
  });
});

describe("filterBoard", () => {
  const mk = (domain: string, count: number): BoardRow => ({
    domain,
    type: "",
    count,
    platforms: 1,
    weight: 0,
  });

  it("剔除引用 < 10 次", () => {
    const out = filterBoard([mk("a.com", 9), mk("b.com", 10), mk("c.com", 49)]);
    expect(out.map((r) => r.domain)).toEqual(["b.com", "c.com"]);
  });

  it("剔除没有网址（空域名 / 无点的聚合桶）", () => {
    const out = filterBoard([mk("smzdm.com", 20), mk("其他来源", 64), mk("", 30)]);
    expect(out.map((r) => r.domain)).toEqual(["smzdm.com"]);
  });

  it("门槛可自定义", () => {
    const out = filterBoard([mk("a.com", 5), mk("b.com", 20)], 20);
    expect(out.map((r) => r.domain)).toEqual(["b.com"]);
  });
});

describe("failReasonLabel", () => {
  it("已知 code 映射人话 + 行动提示", () => {
    expect(failReasonLabel("not_logged_in")).toContain("未登录");
    expect(failReasonLabel("timeout")).toContain("超时");
    expect(failReasonLabel("rate_limited")).toContain("限流");
    expect(failReasonLabel("quota_exhausted")).toMatch(/配额|余额|欠费/);
    expect(failReasonLabel("content_blocked")).toMatch(/内容|拦/);
    expect(failReasonLabel("selector_drift")).toMatch(/改版|页面|采集/);
    expect(failReasonLabel("network")).toMatch(/网络|浏览器/);
    expect(failReasonLabel("interrupted")).toMatch(/中断/);
  });
  it("空 / unknown / 未知 code 回退旧文案「够不到平台」", () => {
    expect(failReasonLabel("")).toBe("够不到平台");
    expect(failReasonLabel("unknown")).toBe("够不到平台");
    expect(failReasonLabel("这不是已知code")).toBe("够不到平台");
  });
});

describe("median (7天滚动中位稳定器)", () => {
  it("奇数取中、偶数取两中均值、乱序先排序", () => {
    expect(median([0.3])).toBe(0.3);
    expect(median([0.5, 0.1, 0.3])).toBe(0.3); // 排序 [.1,.3,.5] 中位 .3
    expect(median([0.2, 0.4, 0.6, 0.8])).toBeCloseTo(0.5); // (.4+.6)/2
  });
  it("空数组返回 null、过滤 NaN", () => {
    expect(median([])).toBeNull();
    expect(median([Number.NaN, 0.4, Number.NaN])).toBe(0.4);
    expect(median([Number.NaN])).toBeNull();
  });
});
