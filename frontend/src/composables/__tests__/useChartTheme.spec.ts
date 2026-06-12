import { describe, it, expect } from "vitest";
import { buildChartTheme, resolveColor } from "../useChartTheme";

const lightReader = (name: string): string =>
  ({
    "--ink-rgb": "28, 26, 23",
    "--ink": "#1c1a17",
    "--ink-3": "#7a7569",
    "--dark": "#1c1a17",
    "--card": "#fbf7ec",
  })[name] ?? "";

const darkReader = (name: string): string =>
  ({
    "--ink-rgb": "245, 237, 224",
    "--ink": "#f3ede0",
    "--ink-3": "#968d7b",
    "--dark": "#f3ede0",
    "--card": "#262019",
  })[name] ?? "";

describe("buildChartTheme", () => {
  it("composes grid from --ink-rgb", () => {
    expect(buildChartTheme(lightReader).grid).toBe("rgba(28, 26, 23, 0.05)");
    expect(buildChartTheme(darkReader).grid).toBe("rgba(245, 237, 224, 0.05)");
  });

  it("uses a fixed faint tooltip border in both modes", () => {
    expect(buildChartTheme(lightReader).tooltipBorder).toBe("rgba(255,255,255,0.1)");
    expect(buildChartTheme(darkReader).tooltipBorder).toBe("rgba(255,255,255,0.1)");
  });

  it("reads direct tokens for tick/tooltip/point/ink", () => {
    const d = buildChartTheme(darkReader);
    expect(d.tick).toBe("#968d7b");
    expect(d.tooltipBg).toBe("#f3ede0");
    expect(d.tooltipFg).toBe("#262019");
    expect(d.pointBorder).toBe("#262019");
    expect(d.ink).toBe("#f3ede0");
  });

  it("falls back to light defaults when a token is missing", () => {
    const empty = buildChartTheme(() => "");
    expect(empty.grid).toBe("rgba(28, 26, 23, 0.05)");
    expect(empty.tick).toBe("#7a7569");
  });
});

describe("resolveColor", () => {
  it("resolves a var() reference via the reader", () => {
    expect(resolveColor("var(--ink)", darkReader)).toBe("#f3ede0");
  });
  it("passes through a literal hex untouched", () => {
    expect(resolveColor("#ee6a2a", darkReader)).toBe("#ee6a2a");
  });
  it("returns the var() string unchanged when the token resolves empty", () => {
    expect(resolveColor("var(--missing)", () => "")).toBe("var(--missing)");
  });
});
