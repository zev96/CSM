import { describe, it, expect } from "vitest";
import { effectiveTheme } from "../useTweaks";

describe("effectiveTheme", () => {
  it("显式 light/dark 原样返回", () => {
    expect(effectiveTheme("light", true)).toBe("light");
    expect(effectiveTheme("dark", false)).toBe("dark");
  });
  it("system 跟随 prefersDark", () => {
    expect(effectiveTheme("system", true)).toBe("dark");
    expect(effectiveTheme("system", false)).toBe("light");
  });
});
