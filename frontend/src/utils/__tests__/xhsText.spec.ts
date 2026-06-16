import { describe, it, expect } from "vitest";
import { buildFullText, countChars } from "@/utils/xhsText";

describe("countChars", () => {
  it("ASCII 按字符数", () => {
    expect(countChars("hello")).toBe(5);
  });
  it("中文按字数", () => {
    expect(countChars("小红书")).toBe(3);
  });
  it("单个 emoji 计 1（码点）", () => {
    expect(countChars("💛")).toBe(1);
    expect(countChars("a💛b")).toBe(3);
  });
  it("空串为 0", () => {
    expect(countChars("")).toBe(0);
  });
});

describe("buildFullText", () => {
  it("标题 + 正文 + 话题用空行拼接，话题加 #", () => {
    expect(buildFullText("标题", "正文内容", ["考证", "干货"])).toBe(
      "标题\n\n正文内容\n\n#考证 #干货",
    );
  });
  it("正文保留内部换行，不被 trim", () => {
    expect(buildFullText("T", "第一行\n第二行", [])).toBe("T\n\n第一行\n第二行");
  });
  it("无标题时跳过标题段", () => {
    expect(buildFullText("", "正文", ["x"])).toBe("正文\n\n#x");
  });
  it("无话题时跳过话题段", () => {
    expect(buildFullText("T", "B", [])).toBe("T\n\nB");
  });
  it("话题去掉空白项，并去掉用户误带的前导 #", () => {
    expect(buildFullText("", "", ["  ", "#已带", "正常"])).toBe("#已带 #正常");
  });
  it("全空返回空串", () => {
    expect(buildFullText("", "", [])).toBe("");
  });
});
