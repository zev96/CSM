import { describe, it, expect } from "vitest";
import { breakpointKind } from "../breakpointBanner";

// R2：断点 banner 按 captcha_signal_layer 分三类。
//  - auth        → 账号未登录/过期（红，带设置链接）
//  - interrupted → R2 崩溃中断（程序退出/崩溃，非风控）
//  - risk        → 其余风控（dom/text/验证码…）
describe("breakpointKind", () => {
  it("auth layer → 'auth'", () => {
    expect(breakpointKind("auth")).toBe("auth");
  });

  it("interrupted layer → 'interrupted'（R2 崩溃恢复，不是风控）", () => {
    expect(breakpointKind("interrupted")).toBe("interrupted");
  });

  it("风控 layer（dom/text/其它）→ 'risk'", () => {
    expect(breakpointKind("dom")).toBe("risk");
    expect(breakpointKind("text")).toBe("risk");
    expect(breakpointKind("captcha")).toBe("risk");
  });

  it("null / undefined / 空 → 'risk'（兜底为通用风控提示）", () => {
    expect(breakpointKind(null)).toBe("risk");
    expect(breakpointKind(undefined)).toBe("risk");
    expect(breakpointKind("")).toBe("risk");
  });
});
