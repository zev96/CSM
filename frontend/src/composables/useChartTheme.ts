/**
 * Chart-theme tokens for chart.js (canvas) — which CANNOT resolve CSS vars.
 * We read the *computed* token values off <body> and rebuild them on every
 * theme flip (data-theme attribute change), so charts re-render in the new
 * palette. SVG charts don't need this — they use var() directly.
 */
import { ref, onMounted, onBeforeUnmount } from "vue";

export interface ChartTheme {
  grid: string;         // axis grid lines
  tick: string;         // axis tick labels
  tooltipBg: string;    // inverted tooltip surface (flips with --dark)
  tooltipFg: string;    // tooltip text (flips with --card)
  tooltipBorder: string;
  pointBorder: string;  // ring around data points = card bg ("cut-out" look)
  ink: string;          // resolved --ink — for "ink" series lines
}

type Reader = (name: string) => string;

/** Pure: build the theme object from a token reader. Testable without a DOM. */
export function buildChartTheme(readVar: Reader): ChartTheme {
  const inkRgb = readVar("--ink-rgb").trim() || "28, 26, 23";
  return {
    grid: `rgba(${inkRgb}, 0.05)`,
    tick: readVar("--ink-3").trim() || "#7a7569",
    tooltipBg: readVar("--dark").trim() || "#1c1a17",
    tooltipFg: readVar("--card").trim() || "#fbf7ec",
    tooltipBorder: `rgba(${inkRgb}, 0.1)`,
    pointBorder: readVar("--card").trim() || "#fbf7ec",
    ink: readVar("--ink").trim() || "#1c1a17",
  };
}

/** Resolve a single `var(--x)` color to its computed value; pass hex through. */
export function resolveColor(c: string, readVar: Reader): string {
  const m = c.match(/^var\((--[\w-]+)\)$/);
  return m ? readVar(m[1]).trim() || c : c;
}

export function useChartTheme() {
  const read: Reader = (name) =>
    getComputedStyle(document.body).getPropertyValue(name);

  const theme = ref<ChartTheme>(buildChartTheme(read));
  let observer: MutationObserver | null = null;

  const refresh = () => {
    theme.value = buildChartTheme(read);
  };

  onMounted(() => {
    refresh(); // re-read after mount (FOUC script may have set theme pre-paint)
    observer = new MutationObserver(refresh);
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
  });
  onBeforeUnmount(() => observer?.disconnect());

  return { theme, resolveColor: (c: string) => resolveColor(c, read) };
}
