import { describe, it, expect } from "vitest";
import {
  normKey,
  buildSpecGroups,
  buildStats,
  productHref,
  stripBrand,
  PARAM_GROUPS,
} from "@/components/materials/modelSpecs";
import type { SpecValue } from "@/stores/materials";

function sv(over: Partial<SpecValue> & { raw: string }): SpecValue {
  return {
    field: over.field ?? "x",
    raw: over.raw,
    numbers: over.numbers ?? [],
    unit: over.unit ?? "",
    is_approx: over.is_approx ?? false,
    is_placeholder: over.is_placeholder ?? false,
  };
}

describe("modelSpecs.normKey", () => {
  it("吃掉空格 + 全角括号→半角，使设计标签与真实字段等价", () => {
    expect(normKey("吸力 (AW)")).toBe(normKey("吸力(AW)"));
    expect(normKey("最低噪音 (dB)")).toBe(normKey("最低噪音（dB）"));
    expect(normKey("HEPA 等级")).toBe(normKey("HEPA等级"));
    expect(normKey("主机重量 (kg)")).toBe(normKey("主机重量(kg)"));
  });
});

describe("modelSpecs.buildSpecGroups", () => {
  // 真实 vault 字段名（含空格/全角括号差异），验证仍能命中设计稿分组
  const specs: Record<string, SpecValue> = {
    "价格": sv({ raw: "839", numbers: [839] }),
    "吸力(AW)": sv({ raw: "220", numbers: [220] }),
    "真空度(Pa)": sv({ raw: "35000", numbers: [35000] }),
    "最低噪音（dB）": sv({ raw: "70dB", numbers: [70] }),
    "HEPA等级": sv({ raw: "PET HEPA14" }),
    "主机重量(kg)": sv({ raw: "1.5kg", numbers: [1.5] }),
    "电机转速": sv({ raw: "无", is_placeholder: true }),
    "自定义奇怪字段": sv({ raw: "某值" }), // 本体未覆盖 → 兜底进「其他」
  };

  it("按 6 组本体分组，字段名差异仍命中", () => {
    const { groups } = buildSpecGroups(specs);
    const base = groups.find((g) => g.title === "基础信息")!;
    const price = base.rows.find((r) => r.label === "价格")!;
    expect(price.value).toBe("839");
    expect(price.dim).toBe(false);

    const perf = groups.find((g) => g.title === "核心性能")!;
    const suction = perf.rows.find((r) => r.label === "吸力 (AW)")!;
    expect(suction.value).toBe("220"); // 命中真实「吸力(AW)」
    expect(suction.dim).toBe(false);

    const noise = groups.find((g) => g.title === "噪音表现")!;
    const lowNoise = noise.rows.find((r) => r.label === "最低噪音 (dB)")!;
    expect(lowNoise.value).toBe("70dB"); // 命中真实「最低噪音（dB）」
  });

  it("缺失/占位字段标 dim 并显示「—」", () => {
    const { groups } = buildSpecGroups(specs);
    const perf = groups.find((g) => g.title === "核心性能")!;
    const rpm = perf.rows.find((r) => r.label === "电机转速")!; // 占位
    expect(rpm.dim).toBe(true);
    expect(rpm.value).toBe("—");
    const inflow = perf.rows.find((r) => r.label === "入口风量")!; // 完全缺失
    expect(inflow.dim).toBe(true);
    expect(inflow.value).toBe("—");
  });

  it("未被本体覆盖且非占位的真实字段兜底进「其他」组", () => {
    const { groups } = buildSpecGroups(specs);
    const other = groups.find((g) => g.title === "其他");
    expect(other).toBeTruthy();
    expect(other!.rows.some((r) => r.label === "自定义奇怪字段" && r.value === "某值")).toBe(true);
  });

  it("进度 filled/total 只统计 6 组内字段，不含「其他」", () => {
    const totalKeys = PARAM_GROUPS.reduce((n, g) => n + g.keys.length, 0);
    const { filled, total } = buildSpecGroups(specs);
    expect(total).toBe(totalKeys); // 与「其他」无关
    // 命中的非占位：价格/吸力/真空度/最低噪音/HEPA/主机重量 = 6
    expect(filled).toBe(6);
  });

  it("占位字段不进「其他」组", () => {
    const only: Record<string, SpecValue> = {
      "怪字段占位": sv({ raw: "无", is_placeholder: true }),
    };
    const { groups } = buildSpecGroups(only);
    expect(groups.find((g) => g.title === "其他")).toBeUndefined();
  });
});

describe("modelSpecs.buildStats", () => {
  it("用抽出的数字 + 设计单位，避免真实值「70dB」拼成双单位", () => {
    const specs: Record<string, SpecValue> = {
      "最低噪音（dB）": sv({ raw: "70dB", numbers: [70] }),
    };
    const stats = buildStats(specs);
    const noise = stats.find((s) => s.label === "最低噪音")!;
    expect(noise.value).toBe("70 dB");
  });

  it("价格加 ¥ 前缀；缺失显示「—」", () => {
    const stats = buildStats({ "价格": sv({ raw: "1999", numbers: [1999] }) });
    expect(stats.find((s) => s.label === "价格")!.value).toBe("¥1999");
    // 其余字段缺失
    expect(stats.find((s) => s.label === "吸力")!.value).toBe("—");
    expect(stats.find((s) => s.label === "吸力")!.dim).toBe(true);
  });

  it("重量 1.5kg → 「1.5 kg」（数字保留小数）", () => {
    const stats = buildStats({ "主机重量(kg)": sv({ raw: "1.5kg", numbers: [1.5] }) });
    expect(stats.find((s) => s.label === "整机重量")!.value).toBe("1.5 kg");
  });
});

describe("modelSpecs.productHref", () => {
  it("已是完整 URL 直接用，不重复拼 https", () => {
    const specs = { "产品链接": sv({ raw: "https://item.jd.com/x.html" }) };
    expect(productHref(specs)).toBe("https://item.jd.com/x.html");
  });
  it("裸链接补 https://", () => {
    const specs = { "产品链接": sv({ raw: "item.jd.com/x.html" }) };
    expect(productHref(specs)).toBe("https://item.jd.com/x.html");
  });
  it("占位/缺失返回 null", () => {
    expect(productHref({ "产品链接": sv({ raw: "无", is_placeholder: true }) })).toBeNull();
    expect(productHref({})).toBeNull();
  });
  it("非 URL 描述文本返回 null（不拼成死链）", () => {
    expect(productHref({ "产品链接": sv({ raw: "京东搜索 XXX" }) })).toBeNull(); // 有空格
    expect(productHref({ "产品链接": sv({ raw: "见官网" }) })).toBeNull(); // 无点
  });
});

describe("modelSpecs.stripBrand", () => {
  it("去掉品牌前缀", () => {
    expect(stripBrand("CEWEYDS18", "CEWEY")).toBe("DS18");
    expect(stripBrand("美的F30S", "美的")).toBe("F30S");
  });
  it("不含前缀时原样返回", () => {
    expect(stripBrand("V15", "戴森")).toBe("V15");
  });
});
