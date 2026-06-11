# 暗色主题 · 核心（②a）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接通明/暗/跟随系统三态主题切换，并加暗色 token 覆盖块，让应用整体（DOM/CSS 表面）在暗色下正确呈现。基于 ③ 的 token 地基——暗色块只翻几个根值（尤其 `--ink-rgb`），所有 `rgba(var(--ink-rgb),α)` 边框/overlay/滚动条/`--line` 自动跟着翻。

**Architecture:** spec 工作流 ②，按"图表(canvas)单独处理"拆分后的 **②a 核心**部分（chart.js 组件的 canvas 颜色不在本 PR，留给 ②b）。改动：(1) `useTweaks.ts` 加 theme 字段 + apply/matchMedia + 持久化；(2) `style.css` 加 `body[data-theme="dark"]` 覆盖块；(3) 全局 `rgba(28,26,23,α)` → `rgba(var(--ink-rgb),α)` 扫尾（排除两个图表组件）；(4) `index.html` FOUC 内联脚本；(5) 设置页主题下拉接通 useTweaks。亮色默认下零视觉变化。

**Tech Stack:** Vue 3 + TS + Vitest + Tauri WebView2（Chromium，支持 `matchMedia` / CSS `var()`）。

**对应 spec：** […unification-design.md](../specs/2026-06-11-frontend-ui-design-system-unification-design.md) 工作流 ②（本 PR = ②a 核心；②b 图表随后）。

**前置：** 当前分支 `claude/dark-theme`（基于含 ③ 的 main）。③ 已建 `--ink-rgb/--green-rgb/--red-rgb` + soft/deep + chrome token，且 `--line/-2`、`--scroll-thumb/-hover` 已基于 `--ink-rgb`。`node_modules` 就绪。

**暖咖 Espresso 暗色色板**已在 spec 决策（Q「主题方向」）确认。

---

## File Structure

- Modify: `frontend/src/composables/useTweaks.ts`（theme 字段 + 解析 + matchMedia + 持久化）
- Modify: `frontend/src/style.css`（加 `body[data-theme="dark"]` 块）
- Modify: `frontend/index.html`（`<body>` 首个子节点加 FOUC 内联脚本）
- Modify: `frontend/src/views/SettingsView.vue`（主题 FormSelect 接 useTweaks）
- Modify: ~30 个含 `rgba(28,26,23,α)` 的 `.vue`（ink-overlay 扫尾；**排除** `LineChart.vue`、`GaugeCard.vue`）
- Create: `frontend/src/composables/__tests__/useTweaks.spec.ts`（effectiveTheme 纯函数单测）

> 工作目录仓库根。npm 脚本前 `cd frontend`。

---

## Task 1: useTweaks 加 theme（TDD 纯函数 + 接线）

**Files:**
- Modify: `frontend/src/composables/useTweaks.ts`
- Test: `frontend/src/composables/__tests__/useTweaks.spec.ts`

- [ ] **Step 1: 写失败测试（纯解析函数）**

Create `frontend/src/composables/__tests__/useTweaks.spec.ts`:
```ts
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/composables/__tests__/useTweaks.spec.ts; cd ..
```
Expected: FAIL（`effectiveTheme` 未导出）。

- [ ] **Step 3: 改 useTweaks.ts**

`useTweaks.ts` 改动（保持其余不变）：
1. 类型 + 默认值：
```ts
export type Theme = "system" | "light" | "dark";

interface Tweaks {
  radius: Radius;
  density: Density;
  primary: string;
  theme: Theme;
}

const DEFAULTS: Tweaks = {
  radius: "medium",
  density: "cozy",
  primary: "#ee6a2a",
  theme: "system",
};
```
2. 导出纯解析函数（apply 与单测共用）：
```ts
/** 把用户偏好 + 系统是否暗色，解析成实际生效主题。纯函数，便于测试。 */
export function effectiveTheme(pref: Theme, prefersDark: boolean): "light" | "dark" {
  return pref === "system" ? (prefersDark ? "dark" : "light") : pref;
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}
```
3. `apply()` 里写 body data-theme：
```ts
function apply() {
  if (typeof document === "undefined") return;
  document.body.dataset.radius = state.radius;
  document.body.dataset.density = state.density;
  document.body.dataset.theme = effectiveTheme(state.theme, systemPrefersDark());
  document.documentElement.style.setProperty("--primary", state.primary);
}
```
4. `load()` 里补读 theme：在 `if (parsed.primary) state.primary = parsed.primary;` 之后加：
```ts
    if (parsed.theme) state.theme = parsed.theme;
```
5. `useTweaks()` 的 booted 块里，`watch(...)` 之后加系统主题监听（system 模式下 OS 切换时实时跟随）：
```ts
    if (typeof window !== "undefined" && window.matchMedia) {
      window
        .matchMedia("(prefers-color-scheme: dark)")
        .addEventListener("change", () => {
          if (state.theme === "system") apply();
        });
    }
```

- [ ] **Step 4: 跑测试确认通过 + 类型**

```bash
cd frontend && npx vitest run src/composables/__tests__/useTweaks.spec.ts && npx vue-tsc -b; cd ..
```
Expected: 2 用例过；0 type errors。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useTweaks.ts frontend/src/composables/__tests__/useTweaks.spec.ts
git commit -m "feat(frontend): useTweaks 支持明/暗/跟随系统主题（apply data-theme + 持久化 + 系统监听）"
```

---

## Task 2: 暗色 token 覆盖块

**Files:**
- Modify: `frontend/src/style.css`

- [ ] **Step 1: 在 `:root {}` 闭合之后追加暗色块**

紧跟 `:root { ... }` 的 `}` 之后插入（与 `body[data-density]` 等同区域）：

```css
/* ── 暗色主题（暖咖 Espresso）──────────────────────────────────────
   只覆盖语义 token；--line/-2、--scroll-thumb/-hover 基于 --ink-rgb，
   翻 --ink-rgb 即自动跟随，无需在此重设。图表(canvas)颜色见 ②b。 */
body[data-theme="dark"] {
  /* 表面 */
  --bg-outer: #14110d;
  --bg-inner: #1b1713;
  --card: #262019;
  --card-2: #2f2820;
  --card-white: #312a21;
  /* 文字 */
  --ink: #f3ede0;
  --ink-2: #c9c0ad;
  --ink-3: #968d7b;
  --ink-4: #6e6657;
  /* rgb 三元：ink 翻成浅纸色 → 所有 rgba(var(--ink-rgb),α) 边框/overlay/滚动条/--line 自动变浅 */
  --ink-rgb: 245, 237, 224;
  /* 主色（略提亮；deep = 暗色 hover 更亮） */
  --primary: #f0732f;
  --primary-soft: #3a2a1c;
  --primary-deep: #f78a4f;
  /* 语义色（底深、文字提亮以保对比） */
  --yellow: #f0c14d;
  --yellow-soft: #3a3320;
  --yellow-deep: #f0c14d;
  --green: #8fae6f;
  --green-rgb: 143, 174, 111;
  --green-soft: #2a3320;
  --green-deep: #a8c489;
  --red: #e06a58;
  --red-rgb: 224, 106, 88;
  --red-soft: #3a2420;
  --red-deep: #f0a094;
  /* 重按钮/重卡：反相成浅色 */
  --dark: #f3ede0;
  --dark-2: #e6dccb;
  /* 磨砂玻璃（离散重设） */
  --frosted-bg: rgba(38, 32, 25, 0.55);
  --frosted-border: rgba(245, 237, 224, 0.08);
}
```

- [ ] **Step 2: 验证（暗色块语法 + 亮色不受影响）**

```bash
cd frontend && npx vue-tsc -b && npm run build; cd ..
```
Expected: build 成功（CSS 解析无误）。亮色默认（无 data-theme 或 light）不读这块，零影响。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/style.css
git commit -m "feat(frontend): 加暗色主题 token 覆盖块（暖咖 Espresso）"
```

---

## Task 3: ink-overlay 扫尾（rgba(28,26,23) → rgba(var(--ink-rgb)))

把散落在组件里的 `rgba(28, 26, 23, α)`（墨色叠加：边框/hover/分隔/阴影）改成 `rgba(var(--ink-rgb), α)`，使其在暗色下自动变浅。亮色值不变（`--ink-rgb` 亮色 = `28, 26, 23`），故亮色零视觉变化。

**Files:** 所有含该字面的 `.vue`，**除** `frontend/src/components/monitor/history/LineChart.vue` 与 `frontend/src/components/home/GaugeCard.vue`（chart.js canvas 颜色，留给 ②b）。

- [ ] **Step 1: 列出待改位置**

```bash
rg -n "rgba\(28, ?26, ?23," frontend/src --glob '!**/LineChart.vue' --glob '!**/GaugeCard.vue'
```
记录命中文件与行。预期约 30 个文件、~79 处。**逐处确认其上下文是 CSS**（inline `:style="{...}"`、`style="..."`、或 `<style>` 块）—— 本扫尾只动 CSS 上下文的字面；若发现某处是传给 chart.js/canvas 的 JS 颜色串（理论上已排除两个图表文件，但仍以此为准），跳过并报告。

- [ ] **Step 2: 逐文件替换**

对每个命中文件，把 `rgba(28, 26, 23, X)` / `rgba(28,26,23,X)` 改为 `rgba(var(--ink-rgb), X)`（X 原样保留）。可用编辑器整文件替换该字面（每个文件内所有出现都是 CSS 上下文时安全）。

- [ ] **Step 3: 验证替换完整 + 亮色不变 + 构建**

```bash
rg -n "rgba\(28, ?26, ?23," frontend/src --glob '!**/LineChart.vue' --glob '!**/GaugeCard.vue'
```
Expected: 零命中（除两个排除的图表文件外，全部已迁移）。
```bash
cd frontend && npx vue-tsc -b && npx vitest run && npm run build; cd ..
```
Expected: 0 type errors；单测全过；build 成功。亮色值未变（`--ink-rgb` 亮色 = 28,26,23），逐像素不变。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(frontend): ink-overlay 字面收编进 --ink-rgb（暗色自动变浅；图表除外）"
```
> 注：本 task 用 `git add -A` 可接受 —— 只动了源码 `.vue`，无构建产物（vite.config 已 gitignore）。提交前用 `git status` 复核没有意外文件。

---

## Task 4: FOUC 防闪 —— index.html 内联脚本

冷启动若 localStorage 选了暗色，必须在首屏渲染前就把 `data-theme` 写到 body，否则会先闪一下亮色。脚本放 `<body>` 的**第一个子节点**（此时 body 已存在、#app 还没渲染）。

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: 在 `<body ...>` 之后、`<div id="app">` 之前插入脚本**

把：
```html
  <body data-density="cozy" data-radius="medium">
    <div id="app"></div>
```
改为：
```html
  <body data-density="cozy" data-radius="medium">
    <script>
      // FOUC 防闪：首屏渲染前依据已存偏好 / 系统设置写 data-theme。
      // 与 useTweaks 的 csm.tweaks.v1 同源；useTweaks 挂载后会再 apply 一次（幂等）。
      (function () {
        try {
          var pref = "system";
          var raw = localStorage.getItem("csm.tweaks.v1");
          if (raw) { var p = JSON.parse(raw); if (p && p.theme) pref = p.theme; }
          var dark =
            pref === "dark" ||
            (pref === "system" &&
              window.matchMedia &&
              window.matchMedia("(prefers-color-scheme: dark)").matches);
          document.body.dataset.theme = dark ? "dark" : "light";
        } catch (e) {
          document.body.dataset.theme = "light";
        }
      })();
    </script>
    <div id="app"></div>
```

- [ ] **Step 2: 验证**

```bash
cd frontend && npm run build; cd ..
```
Expected: build 成功（脚本是静态 HTML，不影响打包）。手动验证留到 Task 6。

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(frontend): 冷启动 FOUC 防闪 —— 首屏前写 data-theme"
```

---

## Task 5: 设置页主题下拉接通 useTweaks

当前 `SettingsView.vue` 的主题 `FormSelect` 绑死占位 `localUI.theme`（不保存不生效）。改绑到 `useTweaks().state.theme`。

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: 引入 useTweaks 并取 state**

在 `<script setup>` 顶部已有的 import 区加：
```ts
import { useTweaks } from "@/composables/useTweaks";
```
在 `const localUI = reactive({...})` 附近加：
```ts
const tweaks = useTweaks();
```

- [ ] **Step 2: 改 FormSelect 绑定**

把主题那行：
```vue
              <FormSelect
                v-model="localUI.theme"
                :options="[
                  { label: '跟随系统', value: 'system' },
                  { label: '明亮', value: 'light' },
                  { label: '暗色', value: 'dark' },
                ]"
                width="140"
              />
```
改为 `v-model="tweaks.state.theme"`（其余不变）。改完后 `localUI` 里的 `theme: "system",` 字段已无人用，一并删除（避免死字段）。

- [ ] **Step 3: 验证**

```bash
cd frontend && npx vue-tsc -b && npx vitest run; cd ..
```
Expected: 0 type errors；单测全过。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(frontend): 设置页主题下拉接通 useTweaks（切换即生效+持久化）"
```

---

## Task 6: 收尾验证（含真机目测）

- [ ] **Step 1: 全量类型 + 单测 + 构建**

```bash
cd frontend
npx vue-tsc -b
npx vitest run
npm run build
cd ..
```
Expected: 0 type errors；全部单测过（含新增 effectiveTheme 用例）；build 成功。

- [ ] **Step 2: 残留 ink 字面核查**

```bash
rg -n "rgba\(28, ?26, ?23," frontend/src --glob '!**/LineChart.vue' --glob '!**/GaugeCard.vue'
```
Expected: 零命中。

- [ ] **Step 3: 真机/dev 目测三态**

起应用（dev 或既有实例）：
- 设置 → 通用 → 主题：切「暗色」→ 全局立刻变暗（背景/卡片/文字/边框/状态药丸/滚动条都翻）；切「明亮」→ 复原；切「跟随系统」→ 跟随 OS。
- 切暗色后**刷新/重启**：仍是暗色（持久化 + FOUC：首屏不闪亮色）。
- 暗色下逐页扫一眼：工作台、监测中心各 tab、数据中心、设置。**已知**：图表(折线/仪表)内部颜色暂未主题化（网格/刻度可能偏淡或不搭）——这是 ②b 的范围，本 PR 不处理。
- 留意有无个别仍用硬编码 hex（如 `#fbf7ec`/`#1c1a17` 写死）的元素在暗色下不搭；记录下来（少量交 ②b 或后续目测修，不阻塞本 PR）。

- [ ] **Step 4: 工作树干净**

```bash
git status --porcelain
```
Expected: 空。

---

## 收尾：开 PR

```bash
git push -u origin claude/dark-theme
gh pr create --base main --fill
```
返回 PR URL，停在 pending 等网页 merge。PR 描述注明：本 PR = ②a 核心暗色；图表(canvas)主题化见后续 ②b。
