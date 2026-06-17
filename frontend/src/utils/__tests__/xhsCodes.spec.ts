import { describe, it, expect } from "vitest";
import { tokenizeXhsCodes } from "@/utils/xhsCodes";

describe("tokenizeXhsCodes", () => {
  it("空串 → 空数组", () => {
    expect(tokenizeXhsCodes("")).toEqual([]);
  });

  it("纯文本 → 单个 text 段", () => {
    expect(tokenizeXhsCodes("今天天气好")).toEqual([{ type: "text", value: "今天天气好", label: "" }]);
  });

  it("单个代码 → label 去掉 []R", () => {
    expect(tokenizeXhsCodes("[害羞R]")).toEqual([{ type: "code", value: "[害羞R]", label: "害羞" }]);
  });

  it("文本夹代码 → text/code/text 三段", () => {
    const segs = tokenizeXhsCodes("开心[偷笑R]结束");
    expect(segs).toEqual([
      { type: "text", value: "开心", label: "" },
      { type: "code", value: "[偷笑R]", label: "偷笑" },
      { type: "text", value: "结束", label: "" },
    ]);
  });

  it("多个代码相邻", () => {
    const segs = tokenizeXhsCodes("[害羞R][色R]");
    expect(segs.map((s) => s.type)).toEqual(["code", "code"]);
    expect(segs.map((s) => s.label)).toEqual(["害羞", "色"]);
  });

  it("非 R 结尾的方括号不当代码", () => {
    expect(tokenizeXhsCodes("[备注]说明")).toEqual([{ type: "text", value: "[备注]说明", label: "" }]);
  });
});
