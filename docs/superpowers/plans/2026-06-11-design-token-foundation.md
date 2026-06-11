# 设计 Token 地基（③）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可主题化的设计 token 地基——把散落的硬编码颜色收编进 token（含 rgb 三元，供半透明色用），并把 Pill/Card 按 Btn 的 CVA 范式系统化，产出 `design-system.md` 规范。为工作流 ②（暗色主题）铺路：② 届时只需在 `[data-theme="dark"]` 翻几个根值即可。

**Architecture:** 这是 spec 工作流 ③ + ② 的"硬编码色收编"部分（合并为一个 PR）。所有新增 token 的**亮色值与原硬编码值数值完全相同**，因此本 PR 在亮色下**零视觉变化**（这是核心验证点）。暗色覆盖块**不在本 PR**（属 ②）。token 命名保持现状不重命名。

**Tech Stack:** Vue 3 + TypeScript + Tailwind 3（CSS 变量映射）+ class-variance-authority + Vitest + @vue/test-utils + ripgrep。

**对应 spec：** [2026-06-11-frontend-ui-design-system-unification-design.md](../specs/2026-06-11-frontend-ui-design-system-unification-design.md) 工作流 ③（+ ② 的硬编码色收编）。

**关键约定（rgb 三元）：** 半透明色不再写死 `rgba(28,26,23,α)`，改写 `rgba(var(--ink-rgb), α)`。暗色阶段只翻 `--ink-rgb` 一个根值，所有 ink 半透明色（边框/overlay/滚动条）一键全翻。同理 `--green-rgb` / `--red-rgb` 管绿/红 tint。

**cn() 说明：** 参考件 `Btn.vue` 直接用 `cva()` 返回串、不经 cn()。本 PR 的 Pill/Card 照此（cva 直出，不引 cn）。`cn.ts` 保留并在 `design-system.md` 里定位为"组件需要合并外部传入 class 时的 twMerge 助手"（shadcn 模式），按需采用，不在本 PR 强行回填。

---

## File Structure

- Modify: `frontend/src/style.css`（`:root` 加 token + 迁移全局 scrollbar/frosted/geo-scroll/floor-scroll 的 rgba 字面）
- Modify: `frontend/tailwind.config.js`（colors 加离散 token 映射）
- Modify: `frontend/src/components/home/StatCard.vue`（pillStyle + scoped rgba → token）
- Modify: `frontend/src/components/monitor/geo/GeoPlatformBlock.vue`（绿/红 tint → `rgba(var(--*-rgb), α)`）
- Modify: `frontend/src/components/ui/Pill.vue`（tone → cva；warn 文字 tokenize）
- Modify: `frontend/src/components/ui/Card.vue`（muted/dark/padless → cva）
- Create: `frontend/src/components/ui/__tests__/Pill.spec.ts`
- Create: `frontend/src/components/ui/__tests__/Card.spec.ts`
- Create: `docs/design-system.md`

> 工作目录默认仓库根 `D:\CSM\.claude\worktrees\focused-varahamihira-60097d`。npm 脚本前先 `cd frontend`。当前分支 `claude/design-token-foundation`（基于含 #95 的 main）。`node_modules` 已就绪（上个 PR 装过）。

---

## Task 1: 新增 token + 迁移 style.css 全局用法

**Files:**
- Modify: `frontend/src/style.css`
- Modify: `frontend/tailwind.config.js`

- [ ] **Step 1: 在 `style.css` 的 `:root` 末尾加 token 块**

⚠ `--density-gap: 16px;` 在文件里出现两次（`:root` 与 `body[data-density="cozy"]`）。**只改 `:root` 那处** —— 用唯一锚点（含 `--radius-pill` 一行）做 Edit。把：

```css
  --radius-pill: 999px;
  --density-pad: 22px;
  --density-gap: 16px;
}
```
替换为（在 `}` 前插入新 token 块）：
```css
  --radius-pill: 999px;
  --density-pad: 22px;
  --density-gap: 16px;

  /* ── 半透明叠加用 rgb 三元 ───────────────────────────────────────
     写法 rgba(var(--ink-rgb), α)。暗色(②)只翻这三个根值，所有
     ink/green/red 半透明色（边框/overlay/tint/滚动条）一键全翻。 */
  --ink-rgb: 28, 26, 23;
  --green-rgb: 122, 155, 94;
  --red-rgb: 216, 90, 72;

  /* ── 状态软色（离散值，非主色低透明可表达，如 StatCard 升降 pill）── */
  --green-soft: #dde7d2;
  --green-deep: #4d6b2f;
  --red-soft: #f3d3cd;
  --red-deep: #a3382a;
  --yellow-deep: #a07a18;

  /* ── chrome（滚动条 / 磨砂玻璃）—— 借 --ink-rgb 自动随主题翻 ── */
  --scroll-thumb: rgba(var(--ink-rgb), 0.18);
  --scroll-thumb-hover: rgba(var(--ink-rgb), 0.32);
  --frosted-bg: rgba(255, 255, 255, 0.55);
  --frosted-border: rgba(255, 255, 255, 0.65);
}
```

> ⚠ Step 2–5：`rgba(28, 26, 23, 0.18)` 等字面在多个选择器里**重复出现**。每次 Edit 的 old_string 必须带上所属选择器的上下文（如整条 `*{...}` 规则、或 `.geo-scroll::-webkit-scrollbar-thumb{...}`），确保唯一命中、不误改其它选择器的同值。

- [ ] **Step 2: 迁移全局滚动条（8px 主滑道）**

`* { ... scrollbar-color: rgba(28, 26, 23, 0.18) transparent; }` → `scrollbar-color: var(--scroll-thumb) transparent;`
`::-webkit-scrollbar-thumb { background-color: rgba(28, 26, 23, 0.18); ... }` → `background-color: var(--scroll-thumb);`
`::-webkit-scrollbar-thumb:hover { background-color: rgba(28, 26, 23, 0.32); }` → `background-color: var(--scroll-thumb-hover);`

- [ ] **Step 3: 迁移第二段 scrollbar 定义（10px，用 --ink-rgb 保留原 .14/.24）**

该段（`::-webkit-scrollbar-thumb { background: rgba(28, 26, 23, 0.14); ... }` 与其 `:hover { background: rgba(28, 26, 23, 0.24); }`）数值非标准档，用 rgb 三元就地保值：
`rgba(28, 26, 23, 0.14)` → `rgba(var(--ink-rgb), 0.14)`；`rgba(28, 26, 23, 0.24)` → `rgba(var(--ink-rgb), 0.24)`。

- [ ] **Step 4: 迁移 `.geo-scroll` 与 `.floor-scroll-idle`**

`.geo-scroll` 的 `scrollbar-color: rgba(28, 26, 23, 0.18) transparent;` → `var(--scroll-thumb) transparent;`；其 `::-webkit-scrollbar-thumb { background: rgba(28, 26, 23, 0.18); ... }` → `var(--scroll-thumb)`；`:hover { background: rgba(28, 26, 23, 0.32); }` → `var(--scroll-thumb-hover)`。
`.floor-scroll-idle::-webkit-scrollbar-thumb { background: rgba(28, 26, 23, 0.18); ... }` → `var(--scroll-thumb)`；其 `:hover { background: rgba(28, 26, 23, 0.32); }` → `var(--scroll-thumb-hover)`。
**不动** `.floor-scroll-active`（橙色 `rgba(238, 106, 42, ...)`，主色装饰、暗色下也成立，保持原样）。

- [ ] **Step 5: 迁移 `.card-frosted`**

```css
.card-frosted {
  background: var(--frosted-bg);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  border: 1px solid var(--frosted-border);
  border-radius: var(--radius-card);
  box-shadow:
    0 1px 0 rgba(var(--ink-rgb), 0.03),
    0 4px 14px rgba(var(--ink-rgb), 0.05);
}
```

- [ ] **Step 6: `tailwind.config.js` colors 加离散 token 映射**

在 `theme.extend.colors` 里，`"red": "var(--red)",` 之后补：

```js
        "green-soft": "var(--green-soft)",
        "green-deep": "var(--green-deep)",
        "red-soft": "var(--red-soft)",
        "red-deep": "var(--red-deep)",
        "yellow-deep": "var(--yellow-deep)",
```

- [ ] **Step 7: 验证（亮色零视觉变化 + 构建）**

```bash
rg -n "rgba\(28, ?26, ?23" frontend/src/style.css
```
Expected: 仅剩允许保留的（若 Step 3 用了 `rgba(var(--ink-rgb)...` 则全局 ink 字面应为 0；`.floor-scroll-active` 是 238,106,42 不在此列）。确认无遗漏的 `rgba(28,26,23,...)` 字面。
```bash
cd frontend && npx vue-tsc -b && npm run build; cd ..
```
Expected: 0 type errors；build 成功。
说明：所有新 token 亮色值 = 原字面值，故亮色渲染逐像素不变；起 dev 目测滚动条/磨砂卡/评论楼滚动条与改前一致即可。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/style.css frontend/tailwind.config.js
git commit -m "feat(frontend): 设计 token 收编硬编码色（rgb 三元 + 状态/ chrome token）"
```

---

## Task 2: 迁移 StatCard 的 pillStyle + scoped rgba

**Files:**
- Modify: `frontend/src/components/home/StatCard.vue`

- [ ] **Step 1: 迁移 `pillStyle` 函数**

把：
```ts
function pillStyle(d: number) {
  if (d > 0) return { background: "#dde7d2", color: "#4d6b2f" };
  if (d < 0) return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}
```
改为：
```ts
function pillStyle(d: number) {
  if (d > 0) return { background: "var(--green-soft)", color: "var(--green-deep)" };
  if (d < 0) return { background: "var(--red-soft)", color: "var(--red-deep)" };
  return { background: "rgba(var(--ink-rgb), 0.06)", color: "var(--ink-2)" };
}
```

- [ ] **Step 2: 迁移 scoped CSS 里的 ink 字面**

该组件 `<style scoped>` 里三处 `rgba(28, 26, 23, 0.04)` / `rgba(28, 26, 23, 0.06)` / `rgba(28, 26, 23, 0.08)` 分别改为 `rgba(var(--ink-rgb), 0.04)` / `0.06` / `0.08`。

- [ ] **Step 3: 验证**

```bash
rg -n "#dde7d2|#f3d3cd|#4d6b2f|#a3382a|rgba\(28" frontend/src/components/home/StatCard.vue
```
Expected: 零命中。
```bash
cd frontend && npx vue-tsc -b && npx vitest run src/components/home/__tests__/StatCard.spec.ts; cd ..
```
Expected: 0 type errors；StatCard 既有单测通过（pillStyle 改的是值不是结构，行为不变）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/home/StatCard.vue
git commit -m "feat(frontend): StatCard 升降 pill / 卡面 ink 改走 token"
```

---

## Task 3: 迁移 GeoPlatformBlock 的绿/红 tint

**Files:**
- Modify: `frontend/src/components/monitor/geo/GeoPlatformBlock.vue`

- [ ] **Step 1: 迁移 tint computed + 红色提示底**

`tint` computed 里：`"rgba(122,155,94,.16)"` → `"rgba(var(--green-rgb), .16)"`；`"rgba(216,90,72,.12)"` → `"rgba(var(--red-rgb), .12)"`。
模板里红色提示条 `background: 'rgba(216,90,72,.08)'` → `'rgba(var(--red-rgb), .08)'`。

- [ ] **Step 2: 验证**

```bash
rg -n "rgba\(122,155,94|rgba\(216,90,72" frontend/src/components/monitor/geo/GeoPlatformBlock.vue
```
Expected: 零命中。
```bash
cd frontend && npx vue-tsc -b; cd ..
```
Expected: 0 type errors。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/monitor/geo/GeoPlatformBlock.vue
git commit -m "feat(frontend): GeoPlatformBlock 绿/红 tint 改走 rgb 三元 token"
```

---

## Task 4: Pill → CVA（TDD）

**Files:**
- Modify: `frontend/src/components/ui/Pill.vue`
- Test: `frontend/src/components/ui/__tests__/Pill.spec.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/ui/__tests__/Pill.spec.ts`:
```ts
import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import Pill from "../Pill.vue";

describe("Pill", () => {
  it("默认 = info tone（中性）", () => {
    const w = mount(Pill, { slots: { default: () => "x" } });
    expect(w.classes()).toContain("bg-card-2");
    expect(w.classes()).toContain("text-ink-3");
  });
  it("ok tone → 绿", () => {
    expect(mount(Pill, { props: { tone: "ok" } }).classes()).toContain("text-green");
  });
  it("warn tone → 黄底 + tokenized 深黄字（不再硬编码 #a07a18）", () => {
    const c = mount(Pill, { props: { tone: "warn" } }).classes();
    expect(c).toContain("bg-yellow-soft");
    expect(c).toContain("text-yellow-deep");
  });
  it("alert / primary tone", () => {
    expect(mount(Pill, { props: { tone: "alert" } }).classes()).toContain("text-red");
    expect(mount(Pill, { props: { tone: "primary" } }).classes()).toContain("text-primary-deep");
  });
  it("保留基础排版 class", () => {
    expect(mount(Pill, { props: { tone: "ok" } }).classes()).toContain("inline-flex");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/ui/__tests__/Pill.spec.ts; cd ..
```
Expected: FAIL（warn 用例失败 —— 当前是 `text-[#a07a18]` 不是 `text-yellow-deep`）。

- [ ] **Step 3: 改 Pill.vue 为 cva**

整文件替换为：
```vue
<script setup lang="ts">
/**
 * Status / label chip. Tone selects the colour scheme.
 *   ok    → green        warn → yellow      alert → red
 *   primary → primary    info → neutral（默认）
 * Variants 用 class-variance-authority，与 Btn.vue 同范式。
 */
import { cva, type VariantProps } from "class-variance-authority";

const pillVariants = cva(
  "inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium leading-none",
  {
    variants: {
      tone: {
        ok: "bg-green/15 text-green",
        warn: "bg-yellow-soft text-yellow-deep",
        alert: "bg-red/15 text-red",
        primary: "bg-primary-soft text-primary-deep",
        info: "bg-card-2 text-ink-3",
      },
    },
    defaultVariants: { tone: "info" },
  },
);

type PillTone = NonNullable<VariantProps<typeof pillVariants>["tone"]>;
defineProps<{ tone?: PillTone }>();
</script>

<template>
  <span :class="pillVariants({ tone })" :style="{ borderRadius: 'var(--radius-pill)' }">
    <slot />
  </span>
</template>
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/components/ui/__tests__/Pill.spec.ts && npx vue-tsc -b; cd ..
```
Expected: 5 个用例全过；0 type errors。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/Pill.vue frontend/src/components/ui/__tests__/Pill.spec.ts
git commit -m "feat(frontend): Pill 改 CVA 变体 + 单测；warn 文字 tokenize"
```

---

## Task 5: Card → CVA（TDD）

**Files:**
- Modify: `frontend/src/components/ui/Card.vue`
- Test: `frontend/src/components/ui/__tests__/Card.spec.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/ui/__tests__/Card.spec.ts`:
```ts
import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import Card from "../Card.vue";

describe("Card", () => {
  it("默认 = 纸面卡 + 边框 + density 内边距", () => {
    const c = mount(Card).classes();
    expect(c).toContain("bg-card");
    expect(c).toContain("border");
    expect(c).toContain("pad-d");
  });
  it("muted → 深一档卡底", () => {
    expect(mount(Card, { props: { muted: true } }).classes()).toContain("bg-card-2");
  });
  it("dark → 暗底亮字、且不画 1px 边框", () => {
    const c = mount(Card, { props: { dark: true } }).classes();
    expect(c).toContain("bg-dark");
    expect(c).toContain("text-card");
    expect(c).not.toContain("border");
  });
  it("padless → 去内边距", () => {
    expect(mount(Card, { props: { padless: true } }).classes()).not.toContain("pad-d");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/ui/__tests__/Card.spec.ts; cd ..
```
Expected: FAIL（组件尚未导出可被这样断言的稳定 class 结构 / 当前 dark 分支带 `border-transparent`，本测试要求 dark 不含 `border`）。

- [ ] **Step 3: 改 Card.vue 为 cva**

整文件替换为：
```vue
<script setup lang="ts">
/**
 * Base card surface。Variants 用 cva（与 Btn.vue 同范式）：
 *   surface: default(纸面) / muted(深一档) / dark(暗底亮字, 无边框)
 *   padding: default(--density-pad) / none(自定义布局)
 * 公开 prop 不变：muted / padless / dark。
 */
import { cva } from "class-variance-authority";

const cardVariants = cva("transition-colors", {
  variants: {
    surface: {
      default: "bg-card border border-line",
      muted: "bg-card-2 border border-line",
      dark: "bg-dark text-card",
    },
    padding: { default: "pad-d", none: "" },
  },
  defaultVariants: { surface: "default", padding: "default" },
});

const props = defineProps<{ muted?: boolean; padless?: boolean; dark?: boolean }>();
const surface = () => (props.dark ? "dark" : props.muted ? "muted" : "default");
</script>

<template>
  <section
    :class="cardVariants({ surface: surface(), padding: padless ? 'none' : 'default' })"
    :style="{ borderRadius: 'var(--radius-card)' }"
  >
    <slot />
  </section>
</template>
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/components/ui/__tests__/Card.spec.ts && npx vue-tsc -b; cd ..
```
Expected: 4 个用例全过；0 type errors。
> 注：dark 卡原本就没有 `border` 工具类（旧代码 `!dark && 'border'`），只是多了个无宽度的 `border-transparent`（无渲染效果）。新版去掉它，dark 卡视觉不变。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/Card.vue frontend/src/components/ui/__tests__/Card.spec.ts
git commit -m "feat(frontend): Card 改 CVA 变体 + 单测"
```

---

## Task 6: 产出 design-system.md 规范

**Files:**
- Create: `docs/design-system.md`

- [ ] **Step 1: 写规范文档**

Create `docs/design-system.md`:
```markdown
# CSM 前端设计系统约定

> 目的：固化设计 token 与组件构建范式，杜绝新增硬编码颜色 / 不一致的变体写法。

## 1. 颜色一律走 token

所有颜色定义在 `frontend/src/style.css` 的 `:root`，并经 `tailwind.config.js` 映射成 Tailwind 类（`bg-card` / `text-ink-2` …）。**禁止**在组件里写死 hex / rgba。

### 不透明色
用语义 token：`--bg-outer/-inner`、`--card/-2/-white`、`--ink/-2/-3/-4`、`--line/-2`、`--primary/-soft/-deep`、`--yellow/-soft/-deep`、`--green/-soft/-deep`、`--red/-soft/-deep`、`--dark/-2`。

### 半透明色（叠加 / tint / overlay）—— 用 rgb 三元
不要写 `rgba(28,26,23,.06)`，写 `rgba(var(--ink-rgb), .06)`。三元根值：
- `--ink-rgb`（墨色，边框/overlay/滚动条）
- `--green-rgb` / `--red-rgb`（状态 tint）

好处：暗色主题（工作流 ②）只在 `body[data-theme="dark"]` 翻这几个根值，所有半透明色一键全翻，无需逐处改。

### chrome token
`--scroll-thumb` / `--scroll-thumb-hover`（滚动条，借 --ink-rgb 自动随主题）、`--frosted-bg` / `--frosted-border`（磨砂玻璃）。

## 2. 组件变体用 CVA

有"变体"的组件用 `class-variance-authority` 把变体矩阵写成声明式表（范本：`ui/Btn.vue`、`ui/Pill.vue`、`ui/Card.vue`）。模板里 `:class="xxxVariants({ ... })"`。不要用 `:class="[a && '...', b && '...']"` 三元链。

## 3. cn() —— 合并外部 class 时用

`lib/cn.ts` = `twMerge(clsx(...))`。当一个组件需要接受调用方传入的 class 并与自身变体类合并（且要 Tailwind 冲突去重）时用它：`:class="cn(xxxVariants({...}), props.class)"`。目前 Btn/Pill/Card 不接受外部 class（用 cva 直出即可），cn() 留作此类"可被覆盖样式"的组件按需采用。

## 4. token 命名不重命名

不迁移到 shadcn 的 `--background/--foreground` 命名 —— 现有语义名已良好且数百处在用。我们采用 shadcn 的**模式**（cva + rgb/通道三元 + cn 助手），不引入 shadcn-vue / reka-ui 依赖。

## 5. 缺失基础件

Tabs / Switch / Popover / Checkbox 等暂未抽成统一原语，按需手写；将来要补时遵循本规范（cva 变体 + token 颜色）。
```

- [ ] **Step 2: Commit**

```bash
git add docs/design-system.md
git commit -m "docs(frontend): 新增设计系统约定 design-system.md"
```

---

## Task 7: 收尾全量验证

- [ ] **Step 1: 迁移文件无残留硬编码色**

```bash
rg -n "#dde7d2|#f3d3cd|#4d6b2f|#a3382a|#a07a18" frontend/src
```
Expected: 零命中（这些值已全部 tokenize）。
```bash
rg -n "rgba\(122,155,94|rgba\(216,90,72" frontend/src/components/monitor/geo/GeoPlatformBlock.vue
```
Expected: 零命中。

- [ ] **Step 2: 全量类型检查 + 单测 + 构建**

```bash
cd frontend
npx vue-tsc -b
npx vitest run
npm run build
cd ..
```
Expected: 0 type errors；全部单测通过（含新增 Pill/Card 用例 + 既有 94 个）；build 成功。

- [ ] **Step 3: 亮色视觉回归（dev 目测）**

起 dev（或既有运行实例）目测：首页 StatCard 升/降 pill 配色、GEO 平台块绿/红 tint、各处滚动条、磨砂卡 —— 均与改前一致（token 亮色值 = 原字面，应逐像素相同）。

- [ ] **Step 4: 工作树干净**

```bash
git status --porcelain
```
Expected: 空。

---

## 收尾：开 PR

```bash
git push -u origin claude/design-token-foundation
gh pr create --base main --fill
```
返回 PR URL，停在 pending 等网页 merge。本 PR 亮色零视觉变化、为 ② 暗色铺好 token 地基。
