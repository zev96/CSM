import { describe, it, expect } from "vitest";
import { assembleFrontmatter, filenameError } from "@/components/materials/payload";

describe("payload helper", () => {
  it("核心关键词 拆成数组、空值丢弃", () => {
    expect(assembleFrontmatter({ 产品: "吸尘器", 核心关键词: "吸力, 续航" }))
      .toEqual({ 产品: "吸尘器", 核心关键词: ["吸力", "续航"] });
    expect(assembleFrontmatter({ 产品: "", 素材类型: "科普选购" }))
      .toEqual({ 素材类型: "科普选购" });
  });
  it("filenameError 规则", () => {
    expect(filenameError("a b.md")).toContain("空格");
    expect(filenameError("a/b.md")).toContain("空格");
    expect(filenameError("a.txt")).toContain(".md");
    expect(filenameError("a.md")).toBe("");
    expect(filenameError("")).toBe("");
  });
});
