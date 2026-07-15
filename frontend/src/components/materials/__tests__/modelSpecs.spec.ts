import { describe, it, expect } from "vitest";
import {
  buildSpecGroups,
  buildStats,
  productHref,
  stripBrand,
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
    section: over.section ?? "",
  };
}

describe("modelSpecs.buildSpecGroups(按笔记真实 H2 小节分组)", () => {
  // 净化器形态:字段带 section,插入序 = 笔记顺序
  const specs: Record<string, SpecValue> = {
    "价格": sv({ raw: "899", numbers: [899], section: "基础信息" }),
    "产品链接": sv({ raw: "https://x.com/1", section: "基础信息" }),
    "颗粒物CADR": sv({ raw: "512m³/h", numbers: [512], section: "核心净化性能" }),
    "甲醛CADR": sv({ raw: "308m³/h", numbers: [308], section: "核心净化性能" }),
    "净化方式": sv({ raw: "无", is_placeholder: true, section: "核心净化性能" }),
  };

  it("小节即分组,保持笔记顺序,字段名原样展示", () => {
    const { groups } = buildSpecGroups(specs);
    expect(groups.map((g) => g.title)).toEqual(["基础信息", "核心净化性能"]);
    const perf = groups[1];
    expect(perf.rows.map((r) => r.label)).toEqual(["颗粒物CADR", "甲醛CADR", "净化方式"]);
    expect(perf.rows[0].value).toBe("512m³/h");
    expect(perf.filled).toBe("2 / 3");
  });

  it("占位字段显示「—」并标 dim;进度分母=真实字段总数", () => {
    const { groups, filled, total } = buildSpecGroups(specs);
    const ph = groups[1].rows.find((r) => r.label === "净化方式")!;
    expect(ph.dim).toBe(true);
    expect(ph.value).toBe("—");
    expect(total).toBe(5);
    expect(filled).toBe(4);
  });

  it("无 section 的字段(旧数据兜底)归入「参数」组", () => {
    const { groups } = buildSpecGroups({ "怪字段": sv({ raw: "1" }) });
    expect(groups[0].title).toBe("参数");
  });

  it("空 specs → 空 groups(上层渲染空态)", () => {
    const { groups, filled, total } = buildSpecGroups({});
    expect(groups).toEqual([]);
    expect(filled).toBe(0);
    expect(total).toBe(0);
  });
});

describe("modelSpecs.buildStats(分产品线精选 + 通用兜底)", () => {
  it("吸尘器精选:数字+设计单位,避免「70dB」双单位;价格加 ¥", () => {
    const specs: Record<string, SpecValue> = {
      "价格": sv({ raw: "1999", numbers: [1999] }),
      "最低噪音（dB）": sv({ raw: "70dB", numbers: [70] }),
      "主机重量(kg)": sv({ raw: "1.5kg", numbers: [1.5] }),
    };
    const stats = buildStats(specs, "吸尘器");
    expect(stats.find((s) => s.label === "价格")!.value).toBe("¥1999");
    expect(stats.find((s) => s.label === "最低噪音")!.value).toBe("70 dB");
    expect(stats.find((s) => s.label === "整机重量")!.value).toBe("1.5 kg");
    expect(stats.find((s) => s.label === "吸力")!.value).toBe("—"); // 缺失恒 5 项
    expect(stats).toHaveLength(5);
  });

  it("净化器精选:显示 raw 原文(区间值/复合单位不失真)", () => {
    const specs: Record<string, SpecValue> = {
      "价格": sv({ raw: "899", numbers: [899] }),
      "颗粒物CADR": sv({ raw: "512m³/h", numbers: [512] }),
      "最低档声功率级噪音": sv({ raw: "30-60dB", numbers: [30, 60] }),
      "适用面积": sv({ raw: "20-80㎡", numbers: [20, 80] }),
    };
    const stats = buildStats(specs, "空气净化器");
    expect(stats.find((s) => s.label === "颗粒物CADR")!.value).toBe("512m³/h");
    expect(stats.find((s) => s.label === "噪音")!.value).toBe("30-60dB");
    expect(stats.find((s) => s.label === "适用面积")!.value).toBe("20-80㎡");
    expect(stats.find((s) => s.label === "价格")!.value).toBe("¥899");
  });

  it("未知产品线兜底:价格优先 + 前 4 个短数值字段,排除链接/占位/长文本", () => {
    const specs: Record<string, SpecValue> = {
      "产品链接": sv({ raw: "https://x.com/9", numbers: [9] }),
      "价格": sv({ raw: "599", numbers: [599] }),
      "转速": sv({ raw: "3000rpm", numbers: [3000] }),
      "描述": sv({ raw: "这是一段很长很长的描述文本超过限制", numbers: [1] }),
      "缺口": sv({ raw: "无", is_placeholder: true }),
      "档位": sv({ raw: "3档", numbers: [3] }),
    };
    const stats = buildStats(specs, "扫地机器人");
    expect(stats[0]).toEqual({ label: "价格", value: "¥599", dim: false });
    expect(stats.map((s) => s.label)).toEqual(["价格", "转速", "档位"]);
  });

  it("未知产品线无可用字段 → 空数组(上层隐藏 stat 行)", () => {
    expect(buildStats({}, "扫地机器人")).toEqual([]);
  });
});

describe("modelSpecs.productHref", () => {
  it("已是完整 URL 直接用,不重复拼 https", () => {
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
  it("非 URL 描述文本返回 null(不拼成死链)", () => {
    expect(productHref({ "产品链接": sv({ raw: "京东搜索 XXX" }) })).toBeNull();
    expect(productHref({ "产品链接": sv({ raw: "见官网" }) })).toBeNull();
  });
});

describe("modelSpecs.stripBrand", () => {
  it("去掉品牌前缀", () => {
    expect(stripBrand("CEWEYDS18", "CEWEY")).toBe("DS18");
    expect(stripBrand("DARZD9", "DARZ")).toBe("D9");
  });
  it("不含前缀时原样返回", () => {
    expect(stripBrand("V15", "戴森")).toBe("V15");
  });
});
