# Dark Theme Finish (②b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete dark-mode coverage for the parts ②a's sweep could not reach — chart.js canvas chrome, SVG charts, and the remaining low-contrast status/text colors — so the app is fully legible in Warm-Espresso dark mode.

**Architecture:** Three independent commit groups. (A) **Charts**: a new `useChartTheme` composable reads *computed* design tokens (canvas can't resolve CSS vars) and re-emits them on every `body[data-theme]` flip; `LineChart.vue` consumes it for grid/ticks/tooltip/point-rings and resolves `var()` series colors; the GaugeCard + GeoTrend SVGs get direct CSS-var swaps. (B) **Text contrast**: dark-on-dark status/delta text flips to `-deep` tokens (which brighten in dark) — backgrounds are left untouched so light mode is pixel-identical; one new `--purple-deep` token is added. (C) **Shadows**: a new `--shadow-rgb` (dark in both modes) replaces `--ink-rgb` in the 18 `boxShadow` sites so drop-shadows stay dark instead of inverting to light glows.

**Tech Stack:** Vue 3 `<script setup>`, chart.js v4 + vue-chartjs, Vitest + @vue/test-utils, vue-tsc, CSS custom properties.

---

## Token additions (reference — defined in Task 6 and Task 9)

In `frontend/src/style.css`:

| Token | `:root` (light) | `body[data-theme="dark"]` |
|---|---|---|
| `--purple-deep` | `#5a3e8c` | `#c4a9e8` |
| `--shadow-rgb` | `28, 26, 23` | `0, 0, 0` |

## Color-swap map (Group B — text only, backgrounds untouched)

| Old hardcoded text color | New token | Rationale |
|---|---|---|
| `#7a5400` | `var(--yellow-deep)` | dark amber → brightens to `#f0c14d` in dark |
| `#8a6a1a`, `#c98a18` | `var(--yellow-deep)` | amber text |
| `#5e7848` | `var(--green-deep)` | positive-delta green |
| `#4d6b2f` | `var(--green-deep)` | green text (light value identical) |
| `#b34d12` | `var(--primary-deep)` | running-orange text |
| `#5a3e8c` | `var(--purple-deep)` | captcha-purple text (light value identical) |
| `var(--red)` (as pill fg) | `var(--red-deep)` | failed-red text contrast |

---

## Task 0: Setup — install deps (worktree has no node_modules)

**Files:** none (environment only)

- [ ] **Step 1: Install**

This fresh worktree has no `frontend/node_modules`. Use npm (NOT pnpm — CI only reads `package-lock.json`; pnpm skips the esbuild postinstall and vitest won't run).

Run: `cd frontend && npm install`

- [ ] **Step 2: Discard the lockfile platform-dep prune**

A fresh `npm install` deletes ~500 lines of other-platform optional deps from the committed `package-lock.json`. This delta must NEVER be committed.

```bash
git -C .. stash push -- frontend/package-lock.json   # from frontend/, repo root is ..
git -C .. stash drop 'stash@{0}'
```

Verify clean: `git -C .. status --porcelain frontend/package-lock.json` → no output.

- [ ] **Step 3: Baseline green**

Run: `cd frontend && npx vue-tsc -b && npx vitest run`
Expected: 0 type errors, all tests pass (105 at last count). This is the baseline before any change.

---

## Task 1: `useChartTheme` composable (Group A)

**Files:**
- Create: `frontend/src/composables/useChartTheme.ts`
- Test: `frontend/src/composables/__tests__/useChartTheme.spec.ts`

The pure builder (`buildChartTheme`) is fully testable without a DOM. The reactive shell wires it to `body[data-theme]` mutations.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/composables/__tests__/useChartTheme.spec.ts
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
  it("composes grid/tooltip-border from --ink-rgb", () => {
    expect(buildChartTheme(lightReader).grid).toBe("rgba(28, 26, 23, 0.05)");
    expect(buildChartTheme(darkReader).grid).toBe("rgba(245, 237, 224, 0.05)");
    expect(buildChartTheme(darkReader).tooltipBorder).toBe("rgba(245, 237, 224, 0.1)");
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
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/composables/__tests__/useChartTheme.spec.ts`
Expected: FAIL — "Failed to resolve import ../useChartTheme" (file doesn't exist yet).

- [ ] **Step 3: Write the composable**

```ts
// frontend/src/composables/useChartTheme.ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/composables/__tests__/useChartTheme.spec.ts`
Expected: PASS (7 assertions).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useChartTheme.ts frontend/src/composables/__tests__/useChartTheme.spec.ts
git commit -m "feat(frontend): useChartTheme — computed chart tokens + theme-flip re-read"
```

---

## Task 2: Rewire `LineChart.vue` to `useChartTheme` (Group A)

**Files:**
- Modify: `frontend/src/components/monitor/history/LineChart.vue`

Replace the hardcoded chrome colors (lines ~91, ~110–113, ~124–137, ~148) with `theme.value.*`, and resolve `var()` series colors via `resolveColor`.

- [ ] **Step 1: Import and instantiate the composable**

After the `Chart.register(...)` block, inside `<script setup>`, add the import near the top with the others:

```ts
import { useChartTheme } from "@/composables/useChartTheme";
```

And after `const props = defineProps<...>()`:

```ts
const { theme, resolveColor } = useChartTheme();
```

- [ ] **Step 2: Resolve series colors + point ring in the `data` computed**

In the `data = computed(() => ({...}))` block, read `theme.value` so the computed re-runs on flip, resolve each series color, and use the themed point ring:

```ts
const data = computed(() => {
  const t = theme.value; // track theme so datasets recompute on flip
  return {
    labels: props.labels,
    datasets: props.series.map((s, i) => {
      const c = resolveColor(s.color);
      return {
        label: s.label,
        borderColor: c,
        backgroundColor: c + "20", // 12% alpha fill
        data: s.data,
        borderWidth: 2.2,
        tension: 0.25,
        pointRadius: props.pointRadius ?? 0,
        pointHoverRadius: Math.max(4, (props.pointRadius ?? 0) + 1),
        pointBackgroundColor: c,
        pointBorderColor: t.pointBorder,
        pointBorderWidth: props.pointRadius ? 1 : 0,
        clip: props.pointRadius ? (false as const) : undefined,
        fill: false,
        yAxisID: props.dualAxis && i === 1 ? "y1" : "y",
      };
    }),
  };
});
```

- [ ] **Step 3: Themed chrome in the `options` computed**

Replace the hardcoded tooltip/scale colors. The `options` computed already references reactive state; add `const t = theme.value;` at its top so it re-runs on flip:

```ts
const options = computed<any>(() => {
  const t = theme.value;
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    layout: { padding: props.padding ?? 0 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: t.tooltipBg,
        titleColor: t.tooltipFg,
        bodyColor: t.tooltipFg,
        borderColor: t.tooltipBorder,
        borderWidth: 1,
        padding: 10,
        boxPadding: 4,
        callbacks: props.yAxisFormatter
          ? { label: (ctx: any) => `${ctx.dataset.label}: ${props.yAxisFormatter!(ctx.parsed.y)}` }
          : undefined,
      },
    },
    scales: {
      x: {
        grid: { color: t.grid },
        ticks: { color: t.tick, font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        ...(typeof props.yMax === "number" ? { max: props.yMax } : {}),
        grid: { color: t.grid },
        ticks: {
          color: props.dualAxis ? resolveColor(props.series[0]?.color || "var(--ink-3)") : t.tick,
          font: { size: 10 },
          callback: props.yAxisFormatter
            ? function (this: any, v: any) { return props.yAxisFormatter!(Number(v)); }
            : undefined,
        },
      },
    } as Record<string, any>,
  };
  if (props.dualAxis) {
    base.scales.y1 = {
      position: "right",
      beginAtZero: true,
      grid: { drawOnChartArea: false },
      ticks: {
        color: resolveColor(props.series[1]?.color || "var(--ink-3)"),
        font: { size: 10 },
      },
    };
  }
  return base;
});
```

- [ ] **Step 4: Verify no hardcoded chrome hex remains**

Run: `cd frontend && rg -n "#1c1a17|#fbf7ec|#7a7569|rgba\(28,26,23" src/components/monitor/history/LineChart.vue`
Expected: only the JSDoc usage-example lines (~9–10) may match the *example* `#1e1c19`/`#ee6a2a` colors in comments — NO matches in the `data`/`options` logic. If the doc-comment example still shows `#1e1c19` for 抖音, update it to `var(--ink)` to model the new convention.

- [ ] **Step 5: Typecheck + commit**

Run: `cd frontend && npx vue-tsc -b`
Expected: 0 errors.

```bash
git add frontend/src/components/monitor/history/LineChart.vue
git commit -m "feat(frontend): LineChart 走 useChartTheme（暗色网格/刻度/tooltip/数据点+var()系列色解析）"
```

---

## Task 3: Theme near-black series colors at the 4 consumers (Group A)

**Files:**
- Modify: `frontend/src/components/monitor/CommentMonitorModule.vue:119`
- Modify: `frontend/src/components/monitor/history/BaiduSEOAnalytics.vue:102`
- Modify: `frontend/src/components/monitor/history/ZhihuRankingPage.vue:94`
- Modify: `frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue:94`

Each passes `#1e1c19` (near-black) as a LineChart series / legend color — invisible on a dark chart. LineChart now resolves `var()`, so swap to `var(--ink)`.

- [ ] **Step 1: Swap each `#1e1c19` → `var(--ink)`**

- `BaiduSEOAnalytics.vue:102` — `{ label: "异动关键词数", color: "#1e1c19", ... }` → `color: "var(--ink)"`
- `ZhihuRankingPage.vue:94` — `{ label: "异动问题数", color: "#1e1c19", ... }` → `color: "var(--ink)"`
- `ZhihuSearchAnalyticsPage.vue:94` — `{ label: "异动关键词数", color: "#1e1c19", ... }` → `color: "var(--ink)"`
- `CommentMonitorModule.vue:119` — `{ k: "douyin", l: "抖音", color: "#1e1c19", count: 0 }` → `color: "var(--ink)"`
  - First confirm this `color` field feeds LineChart series and/or a `:style` legend dot (both resolve `var()` fine). It does not need to stay a literal hex.

- [ ] **Step 2: Verify no `#1e1c19` series colors remain**

Run: `cd frontend && rg -n "#1e1c19" src/components/monitor`
Expected: no matches (the LineChart JSDoc example was handled in Task 2).

- [ ] **Step 3: Typecheck + commit**

Run: `cd frontend && npx vue-tsc -b`
Expected: 0 errors.

```bash
git add frontend/src/components/monitor/CommentMonitorModule.vue \
        frontend/src/components/monitor/history/BaiduSEOAnalytics.vue \
        frontend/src/components/monitor/history/ZhihuRankingPage.vue \
        frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue
git commit -m "fix(frontend): 折线图近黑系列色 #1e1c19 → var(--ink)（暗色下不再隐形）"
```

---

## Task 4: GaugeCard.vue SVG ink overlays (Group A)

**Files:**
- Modify: `frontend/src/components/home/GaugeCard.vue` (lines 33, 72, 97, 110, 112, 116)

SVG resolves CSS vars directly — straight swaps.

- [ ] **Step 1: Swap the 5 ink overlays + the arc mid color**

- Line 33: `pct.value >= 20 ? "#e8a04a"` → `pct.value >= 20 ? "var(--yellow)"`
- Line 72: `stroke="rgba(28,26,23,0.08)"` → `stroke="rgba(var(--ink-rgb),0.08)"`
- Line 97: `{ background: 'rgba(28,26,23,0.06)', color: 'var(--ink-2)' }` → `background: 'rgba(var(--ink-rgb),0.06)'`
- Line 110: `background: rgba(28, 26, 23, 0.04);` → `background: rgba(var(--ink-rgb), 0.04);`
- Line 112: `border: 1px solid rgba(28, 26, 23, 0.06);` → `border: 1px solid rgba(var(--ink-rgb), 0.06);`
- Line 116: `background: rgba(28, 26, 23, 0.08);` → `background: rgba(var(--ink-rgb), 0.08);`

- [ ] **Step 2: Verify**

Run: `cd frontend && rg -n "rgba\(28, ?26, ?23|#e8a04a" src/components/home/GaugeCard.vue`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/home/GaugeCard.vue
git commit -m "fix(frontend): GaugeCard 5 处硬编码 ink 叠加 + 弧中段色走 token（暗色化）"
```

---

## Task 5: GeoTrend selected-tab legibility (Group A)

**Files:**
- Modify: `frontend/src/components/monitor/geo/charts/GeoTrend.vue:222`

The selected metric tab uses `background: var(--ink)` (flips to light `#f3ede0` in dark) with `color: '#fff'` → white-on-near-white = invisible in dark. The contrasting text for an `--ink` background is `--card` (flips opposite, so it's always readable). Same fix pattern as ②a's `var(--dark)` legibility pass.

> GeoScatter's white point-halos (`#fff` / `rgba(255,255,255,.6)`, lines 80/114) are LEFT intentionally — white halos separate points on both light and dark scatter areas. GeoGauge has no hardcoded colors. Flag GeoScatter for visual QA.

- [ ] **Step 1: Swap**

Line 222: `color: metric === m.k ? '#fff' : 'var(--ink-2)',` → `color: metric === m.k ? 'var(--card)' : 'var(--ink-2)',`

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/monitor/geo/charts/GeoTrend.vue
git commit -m "fix(frontend): GeoTrend 选中 tab 文字 #fff → var(--card)（var(--ink) 底暗色翻转可读）"
```

---

## Task 6: Add `--purple-deep` token (Group B)

**Files:**
- Modify: `frontend/src/style.css` (`:root` near line 47; `body[data-theme="dark"]` near line 88)

Captcha-waiting status is the only purple; it needs a deep token so its text brightens in dark.

- [ ] **Step 1: Add to `:root`**

After `--yellow-deep: #a07a18;` (line 47):

```css
  --purple-deep: #5a3e8c;
```

- [ ] **Step 2: Add to the dark block**

After the dark `--red-deep: #f0a094;` (line 88):

```css
  --purple-deep: #c4a9e8;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/style.css
git commit -m "feat(frontend): 新增 --purple-deep token（验证码状态紫，暗色翻亮）"
```

---

## Task 7: TaskListItem STATUS_TONE — flip fg to -deep tokens (Group B)

**Files:**
- Modify: `frontend/src/components/mining/TaskListItem.vue:145-153`

Leave every `bg` (the faint rgba tints read fine on the dark base); only flip the `fg` text colors so they brighten in dark. `pending` is already themed.

- [ ] **Step 1: Apply the fg swaps**

```ts
const STATUS_TONE: Record<DerivedStatus, { bg: string; fg: string }> = {
  pending: { bg: "rgba(var(--ink-rgb),0.08)", fg: "var(--ink-3)" },
  running: { bg: "rgba(238,106,42,0.16)", fg: "var(--primary-deep)" },
  // 需验证：紫色 — 跟 抓取中 / 失败 / 进行中 都拉开（用户一眼能区分"轮到我操作了"）
  captcha_waiting: { bg: "rgba(124,77,180,0.18)", fg: "var(--purple-deep)" },
  failed: { bg: "rgba(196,68,57,0.16)", fg: "var(--red-deep)" },
  // 进行中：黄色（暖告知"等用户操作"，跟 抓取中 的橙红区分开）
  in_progress: { bg: "rgba(245,192,66,0.20)", fg: "var(--yellow-deep)" },
  // 已完成：绿色，跟旧 done 同色
  fully_completed: { bg: "rgba(96,138,72,0.18)", fg: "var(--green-deep)" },
  done_empty: { bg: "rgba(96,138,72,0.18)", fg: "var(--green-deep)" },
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/mining/TaskListItem.vue
git commit -m "fix(frontend): TaskListItem 状态色 fg → -deep token（底色不动，暗色翻亮）"
```

---

## Task 8: Remaining low-contrast text → -deep tokens (Group B)

**Files (each is a one-line text-color swap; backgrounds untouched):**
- `frontend/src/views/RecentHistoryView.vue:290` — `'#7a5400'` → `'var(--yellow-deep)'`
- `frontend/src/components/mining/CommentComposer.vue:542` — `isSuggesting ? 'var(--ink-4)' : '#7a5400'` → `... : 'var(--yellow-deep)'`
- `frontend/src/components/mining/VideoDetailPanel.vue:379` — `style="color: #7a5400"` → `style="color: var(--yellow-deep)"`
- `frontend/src/components/mining/VideoDetailPanel.vue:386` — `color: '#7a5400',` → `color: 'var(--yellow-deep)',`
- `frontend/src/components/mining/VideoDetailPanel.vue:376` — icon badge `background: var(--dark); color: var(--yellow);` → `background: var(--yellow-soft); color: var(--yellow-deep);` (var(--dark) flips to light in dark → yellow icon unreadable; a yellow-soft/deep badge themes cleanly both ways)
- `frontend/src/components/mining/PlatformPickerCard.vue:64` — `loggedIn ? '#4d6b2f' : 'var(--red)'` → `loggedIn ? 'var(--green-deep)' : 'var(--red)'`
- `frontend/src/components/monitor/geo/GeoCoverageBoard.vue:169` — `row.scoreDelta > 0 ? '#5e7848' : 'var(--red)'` → `... ? 'var(--green-deep)' : 'var(--red)'`
- `frontend/src/components/monitor/geo/GeoOverviewBar.vue:38` — `v > 0 ? "#5e7848" : ...` → `v > 0 ? "var(--green-deep)" : ...`
- `frontend/src/components/monitor/geo/GeoHero.vue:91` — `color: '#8a6a1a'` → `color: 'var(--yellow-deep)'`
- `frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue:164` — `... ? '#5e7848' : 'var(--ink-3)'` → `... ? 'var(--green-deep)' : 'var(--ink-3)'`
- `frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue:183` — `:style="{ color: '#5e7848' }"` → `'var(--green-deep)'`
- `frontend/src/components/monitor/history/ZhihuRankingPage.vue:183` — `:style="{ color: '#5e7848' }"` → `'var(--green-deep)'`
- `frontend/src/components/monitor/history/BaiduSEOAnalytics.vue:188` — `:style="{ color: '#5e7848' }"` → `'var(--green-deep)'`
- `frontend/src/components/monitor/history/BaiduSEOAnalytics.vue:194` — `:style="{ color: '#c98a18' }"` → `'var(--yellow-deep)'`

- [ ] **Step 1: Apply all swaps above**

Use the color-swap map at the top of this plan. Each is a literal text-color replacement; do NOT touch any `background`, `border`, glow, or `rgba(...)` tint on those lines except the explicit VideoDetailPanel:376 badge case.

- [ ] **Step 2: Verify the targeted hexes are gone**

Run: `cd frontend && rg -n "#7a5400|#5e7848|#8a6a1a|#c98a18" src/views src/components`
Expected: no matches. (`#4d6b2f` and `#5a3e8c` may still appear ONLY as token *values* inside `style.css` — that's correct; they must not appear in components/views.)

Run: `cd frontend && rg -n "#4d6b2f|#5a3e8c|#b34d12" src/components src/views`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add -A frontend/src/views frontend/src/components
git commit -m "fix(frontend): 剩余低对比状态/增量文字 → -deep token（底色不动，暗色全部翻亮）"
```

---

## Task 9: Shadows — `--shadow-rgb` so drop-shadows stay dark (Group C)

**Files:**
- Modify: `frontend/src/style.css` (`:root` + dark block)
- Modify the 18 `boxShadow` sites listed below (swap `var(--ink-rgb)` → `var(--shadow-rgb)`):
  - `components/forms/FormSelect.vue:162`
  - `components/home/CreateArticleHero.vue:163, 208, 246`
  - `components/mining/PlatformChip.vue:29`
  - `components/mining/TaskListItem.vue:378`
  - `components/mining/VideoDetailPanel.vue:276`
  - `components/templates/BlockEditor.vue:736`
  - `components/templates/CascadePicker.vue:131`
  - `components/ui/ToastContainer.vue:42`
  - `views/ArticleView.vue:1722, 2036`
  - `views/MiningView.vue:431`
  - `views/TemplatesView.vue:322, 447, 524, 583`

`rgba(var(--ink-rgb),α)` shadows invert to *light* glows in dark mode (ink flips light). Drop-shadows should stay dark in both themes.

- [ ] **Step 1: Add the token to `style.css`**

In `:root` (next to the other `-rgb` triats, e.g. after `--green-rgb`):

```css
  --shadow-rgb: 28, 26, 23;
```

In `body[data-theme="dark"]`:

```css
  --shadow-rgb: 0, 0, 0;
```

- [ ] **Step 2: Swap the 18 boxShadow sites**

In each file/line above, replace `rgba(var(--ink-rgb),` with `rgba(var(--shadow-rgb),` **only inside `boxShadow` / `box-shadow` values**. Do not touch borders, backgrounds, or other `var(--ink-rgb)` uses on adjacent lines.

- [ ] **Step 3: CreateArticleHero frosted check**

While in `CreateArticleHero.vue`, confirm its frosted surface uses `var(--frosted-bg)` / `var(--frosted-border)` (already themed in ②a). If it hardcodes `rgba(255,255,255,…)` for the glass, swap to the frosted tokens. If it already uses them, no change.

- [ ] **Step 4: Verify no boxShadow still uses ink-rgb**

Run: `cd frontend && rg -n "boxShadow|box-shadow" src | rg "var\(--ink-rgb\)"`
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src
git commit -m "fix(frontend): 投影改用 --shadow-rgb（暗色保持深色投影，不再翻成亮光晕）"
```

---

## Task 10: Full verification + push

- [ ] **Step 1: Typecheck**

Run: `cd frontend && npx vue-tsc -b`
Expected: 0 errors.

> Note: `vue-tsc -b` may emit `vite.config.js` and `*.d.ts` build artifacts. After it passes, restore them: `git checkout -- frontend/vite.config.js frontend/src/*.d.ts 2>/dev/null` (only if they show as modified/untracked).

- [ ] **Step 2: Tests**

Run: `cd frontend && npx vitest run`
Expected: all pass (baseline 105 + the new `useChartTheme` file = 108).

- [ ] **Step 3: Confirm lockfile not dirtied**

Run: `git status --porcelain frontend/package-lock.json`
Expected: no output. If it shows modified, stash+drop it (see Task 0 Step 2).

- [ ] **Step 4: Push + open PR**

```bash
git push -u origin claude/dark-theme-finish
gh pr create --title "feat(frontend): 暗色收尾 — 图表/SVG token 化 + 低对比文字 + 投影" \
  --body "完成 ②b：图表 canvas 主题化（useChartTheme）、SVG 图表、剩余低对比状态/文字、投影色。详见 docs/superpowers/plans/2026-06-12-dark-theme-finish.md" \
  --base main
```

Return the PR URL and stop at pending for web merge.

- [ ] **Step 5: User visual QA (cannot be automated)**

Ask the user to toggle Settings → 主题 → 暗色 and spot-check: 留存/知乎/百度 折线图 (grid/线/tooltip), 首页 GEO 仪表盘, GEO 趋势/散点图, 挖掘任务状态药丸, 各页 ↑增量绿字 / AI 速览 琥珀字, 卡片投影深浅, CreateArticleHero 毛玻璃。

---

## Self-Review

**1. Spec coverage** (against ②b scope = charts + GEO/Gauge SVG + low-contrast text, user chose "全做 1+2+3"):
- Chart.js canvas theming → Tasks 1–3 ✓
- GaugeCard SVG → Task 4 ✓
- GEO SVG charts → Task 5 ✓ (GeoTrend fixed; GeoScatter/GeoGauge assessed & justified)
- Low-contrast status/text sweep → Tasks 6–8 ✓ (incl. the 4 earlier-flagged sites: CommentComposer, VideoDetailPanel, TaskListItem, PlatformPickerCard)
- Shadow inversion (flagged in ②a follow-ups) → Task 9 ✓

**2. Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every swap has exact file:line and before→after. ✓

**3. Type consistency:** `buildChartTheme`/`resolveColor`/`ChartTheme`/`useChartTheme` names match between Task 1 (def), its test, and Task 2 (consumption). `theme.value.*` field names (`grid/tick/tooltipBg/tooltipFg/tooltipBorder/pointBorder/ink`) are identical in the interface, the test, and LineChart usage. ✓

**Design guard — zero light-mode change:** Group B touches only text/fg colors (light values are equal or near-equal to the originals); all tint backgrounds are untouched. Group C's `--shadow-rgb` light value (28,26,23) equals the old `--ink-rgb` light value, so light shadows are pixel-identical. Only Task 8's VideoDetailPanel:376 badge intentionally changes a small icon-chip background — flagged for QA.
