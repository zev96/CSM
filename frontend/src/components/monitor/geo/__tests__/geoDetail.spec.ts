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
  targetRankOnPlatform,
  competitorRankOnPlatform,
  cellStatus,
  deriveCompetitors,
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

describe("targetRankOnPlatform", () => {
  it("提及且有顺位 → 用 cell.rank（与概览卡一致）", () => {
    expect(targetRankOnPlatform(vm("tongyi", { mentioned: true, rank: 1 }))).toBe(1);
    expect(targetRankOnPlatform(vm("tongyi", { mentioned: true, rank: 3 }))).toBe(3);
  });

  it("未提及 → 0（即便 recommended 残留 is_target 位次也不上榜；复现千问 bug）", () => {
    // cell 判「未提及」，但 recommended 里因别名/旧数据残留一个 is_target@1。
    // 热力矩阵必须以 mentioned 为准 → 0（·），不能显示 #1。
    const p = vm("tongyi", {
      mentioned: false,
      rank: -1,
      recommended: [{ name: "CEWEY DS18", position: 1, is_target: true }],
    });
    expect(targetRankOnPlatform(p)).toBe(0);
  });

  it("提及但无有效顺位（rank<=0）→ 0", () => {
    expect(targetRankOnPlatform(vm("tongyi", { mentioned: true, rank: -1 }))).toBe(0);
    expect(targetRankOnPlatform(vm("tongyi", { mentioned: true, rank: 0 }))).toBe(0);
  });
});

describe("competitorRankOnPlatform", () => {
  it("按归一化键匹配，取该平台最优位次（不是碰到的第一条）", () => {
    const p = vm("doubao", {
      recommended: [
        { name: "戴森 V12", position: 7, is_target: false },
        { name: "戴森V12", position: 1, is_target: false },
      ],
    });
    expect(competitorRankOnPlatform(p, "戴森V12")).toBe(1);
    expect(competitorRankOnPlatform(p, "戴森 V12")).toBe(1);
  });
  it("第一条 position=0（LLM 漏给位次）不能把它当成「未上榜」", () => {
    const p = vm("doubao", {
      recommended: [
        { name: "戴森", position: 0, is_target: false },
        { name: "戴森", position: 2, is_target: false },
      ],
    });
    expect(competitorRankOnPlatform(p, "戴森")).toBe(2);
  });
  it("未上榜 → 0", () => {
    const p = vm("doubao", { recommended: [{ name: "追觅", position: 1, is_target: false }] });
    expect(competitorRankOnPlatform(p, "戴森")).toBe(0);
  });
});

describe("cellStatus 提及但未入榜（rank<=0）", () => {
  it("mentioned=true, rank=-1 → 「已提及」而非破损的「提及 #-1」", () => {
    const s = cellStatus(vm("t", { mentioned: true, rank: -1 }));
    expect(s.kind).toBe("hit");
    expect(s.label).toBe("已提及");
    expect(s.label).not.toContain("-1");
  });
  it("mentioned=true, rank=0 → 「已提及」", () => {
    expect(cellStatus(vm("t", { mentioned: true, rank: 0 })).label).toBe("已提及");
  });
  it("mentioned=true, rank>=2 → 「提及 #N」（正常排名不受影响）", () => {
    expect(cellStatus(vm("t", { mentioned: true, rank: 2 })).label).toBe("提及 #2");
  });
  it("mentioned=true, rank=1 → 「首推 #1」", () => {
    expect(cellStatus(vm("t", { mentioned: true, rank: 1 })).label).toBe("首推 #1");
  });
});

describe("deriveCompetitors：is_target 仅在 mentioned 时排除", () => {
  it("未提及的 cell 里残留的 is_target 按普通竞品处理（复现千问脏数据）", () => {
    const p = vm("tongyi", {
      mentioned: false,
      recommended: [{ name: "CEWEY DS18", position: 1, is_target: true }],
    });
    expect(deriveCompetitors([p]).map((c) => c.name)).toContain("CEWEY DS18");
  });
  it("同一竞品的不同写法（差空格/大小写）跨平台合并成一行（复现「希亦 V800」/「希亦V800」重复）", () => {
    const tongyi = vm("tongyi", {
      mentioned: true, rank: 1,
      recommended: [{ name: "希亦 V800", position: 4, is_target: false }],
    });
    const doubao = vm("doubao", {
      mentioned: true, rank: 11,
      recommended: [{ name: "希亦V800", position: 2, is_target: false }],
    });
    const kimi = vm("kimi", {
      mentioned: true, rank: 2,
      recommended: [{ name: "希亦 V800", position: 1, is_target: false }],
    });
    const comp = deriveCompetitors([tongyi, doubao, kimi]);
    expect(comp).toHaveLength(1);              // 只剩一行，不再重复
    expect(comp[0].appears).toBe(3);           // 三个平台都算它出现
    expect(comp[0].avgRank).toBeCloseTo((4 + 2 + 1) / 3);
  });

  it("同一平台把同一竞品列了多条（多型号）→ 只按该平台最优位次计一次，avgRank 不被拉高", () => {
    const doubao = vm("doubao", {
      mentioned: true, rank: 3,
      recommended: [
        { name: "戴森 V12", position: 4, is_target: false },
        { name: "戴森V12", position: 1, is_target: false }, // 同一条，仅空格不同
      ],
    });
    const tongyi = vm("tongyi", {
      mentioned: true, rank: 2,
      recommended: [{ name: "戴森 V12", position: 1, is_target: false }],
    });
    const kimi = vm("kimi", {
      mentioned: true, rank: 5,
      recommended: [{ name: "戴森 V12", position: 2, is_target: false }],
    });
    const comp = deriveCompetitors([doubao, tongyi, kimi]);
    expect(comp).toHaveLength(1);
    expect(comp[0].appears).toBe(3);
    // 豆包取该平台最优位次 1（不是 4），且同平台的两条只计一次 → (1+1+2)/3
    expect(comp[0].avgRank).toBeCloseTo((1 + 1 + 2) / 3);
    expect(comp[0].name).toBe("戴森 V12"); // 展示名取出现次数最多的写法（2 票 vs 1 票）
  });

  it("已提及的 cell 里 is_target 仍作为「你」排除，不混进竞品", () => {
    const p = vm("doubao", {
      mentioned: true,
      rank: 2,
      recommended: [
        { name: "希喂", position: 2, is_target: true },
        { name: "戴森", position: 1, is_target: false },
      ],
    });
    const names = deriveCompetitors([p]).map((c) => c.name);
    expect(names).toContain("戴森");
    expect(names).not.toContain("希喂");
  });
});

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
