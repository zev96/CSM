# 监控页 UX 重设计 ①·第一页（知乎监测）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把知乎监测页从 `lg:grid-cols-[1.4fr_1fr]` 改成 GEO 式两栏（新建 `SplitPane.vue` 壳 `340px 1fr`）：左栏瘦成「名称+副标 / 状态 Pill / ⋯ 菜单」的 GEO 式导航，右栏加宽并重排（L1 选中批次=汇总，L2 选中问题=详情）。本页是 ① 四页改造的**模板页**，建立 SplitPane + ⋯ + 左右栏模式供后 3 页复用。

**Architecture:** 新增可复用 `SplitPane.vue`（GEO 比例固化一处）。左栏 3 列（`1.5fr .9fr 1.1fr`）行模板照搬 GEO `GeoTaskModule`，操作 3 图标 → `Dropdown.vue` 的 ⋯ 菜单。新增聚合 KPI（命中问题数/平均卡位/自家命中数）抽成**纯函数 + 单测**（数据全来自现有 `taskSnapshots`，无后端改动）。右栏 L1 汇总（KPI 四联+概览表+导出/定时）与 L2 详情（KPI 五联+趋势左/列表右）按设计 spec 4.3.1 重排，趋势继续用现有 `LineChart`。

**Tech Stack:** Vue 3 `<script setup>`, Tailwind, Vitest + @vue/test-utils, vue-tsc, 现有 `Dropdown.vue` / `Pill.vue` / `LineChart.vue`。

**设计依据:** spec `docs/superpowers/specs/2026-06-11-frontend-ui-design-system-unification-design.md` §4.1/§4.2/§4.3.1。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/src/components/ui/SplitPane.vue` | 两栏壳（GEO 比例固化，窄屏堆叠，#left/#right 插槽） | **新建** |
| `frontend/src/components/ui/__tests__/SplitPane.spec.ts` | 壳渲染/插槽/窄屏类测试 | **新建** |
| `frontend/src/lib/monitor-zhihu-kpi.ts` (跟随 `monitor-batch`/`monitor-snapshot` 同目录) | 批次聚合 KPI 纯函数 | **新建** |
| `frontend/src/lib/__tests__/monitor-zhihu-kpi.spec.ts` | 聚合 KPI 单测 | **新建** |
| `frontend/src/components/monitor/ZhihuMonitorModule.vue` | 知乎页：接壳 + 左栏瘦身 + 右栏 L1/L2 重排 | 改（Task 3/4/5） |

> `monitor-batch` 实际目录：实现前先 `rg "from .*monitor-batch"` 确认（约 `@/lib/monitor-batch` 或 `@/utils/monitor-batch`），新 kpi 文件放同目录、同 import 风格。

---

## Task 1: SplitPane.vue 共享壳

**Files:**
- Create: `frontend/src/components/ui/SplitPane.vue`
- Test: `frontend/src/components/ui/__tests__/SplitPane.spec.ts`

把 GEO 的 `gridTemplateColumns:'340px 1fr', gap:'18px'` + 窄屏单列堆叠固化到一处。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/components/ui/__tests__/SplitPane.spec.ts
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import SplitPane from "../SplitPane.vue";

describe("SplitPane", () => {
  it("renders #left and #right slots", () => {
    const w = mount(SplitPane, {
      slots: { left: "<div class='L'>L</div>", right: "<div class='R'>R</div>" },
    });
    expect(w.find(".L").exists()).toBe(true);
    expect(w.find(".R").exists()).toBe(true);
  });

  it("applies the default GEO column template (340px 1fr) and gap", () => {
    const w = mount(SplitPane, { slots: { left: "l", right: "r" } });
    const style = w.attributes("style") ?? "";
    expect(style).toContain("340px 1fr");
    expect(style).toContain("18px");
  });

  it("honors custom leftWidth / gap props", () => {
    const w = mount(SplitPane, {
      props: { leftWidth: "300px", gap: "12px" },
      slots: { left: "l", right: "r" },
    });
    const style = w.attributes("style") ?? "";
    expect(style).toContain("300px 1fr");
    expect(style).toContain("12px");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/ui/__tests__/SplitPane.spec.ts`
Expected: FAIL（"Failed to resolve import ../SplitPane.vue"）。

- [ ] **Step 3: 写 SplitPane.vue**

```vue
<script setup lang="ts">
/**
 * 监控页两栏壳 —— 把 GEO 的两栏比例固化在一处（左栏定宽导航 + 右栏自适应详情）。
 * lg 以下退化为单列堆叠（窄屏左右改上下）。各页只填 #left / #right。
 *
 * 用法：
 *   <SplitPane>
 *     <template #left> ...任务/列表导航... </template>
 *     <template #right> ...详情... </template>
 *   </SplitPane>
 */
defineProps<{
  /** 左栏宽度，默认 GEO 口径 340px。 */
  leftWidth?: string;
  /** 两栏间距，默认 18px。 */
  gap?: string;
}>();
</script>

<template>
  <div class="split-pane grid min-h-0 flex-1 grid-cols-1" :style="{ gap: gap ?? '18px' }">
    <div class="split-pane__left min-h-0"><slot name="left" /></div>
    <div class="split-pane__right min-h-0"><slot name="right" /></div>
  </div>
</template>

<style scoped>
/* lg(1024px) 及以上才进两栏；以下单列堆叠（grid-cols-1 默认即堆叠）。
   列模板用 CSS 变量注入，默认 340px 1fr。 */
.split-pane {
  --split-left: v-bind('leftWidth ?? "340px"');
}
@media (min-width: 1024px) {
  .split-pane {
    grid-template-columns: var(--split-left) 1fr;
  }
}
</style>
```

> 注：测试断言 `style` 含 `340px 1fr` —— `v-bind` 在 scoped style 里编译成内联 `--split-left` 变量但**不会**让 `grid-template-columns` 出现在元素 `style` 属性里。为让单测能断言列模板，改为**把列模板写进内联 `:style`**而非 media query，用 JS 控制窄屏：见 Step 3b 修正版（优先用 3b）。

- [ ] **Step 3b: SplitPane.vue（最终版 —— 列模板进内联 style，便于测试 + 窄屏用容器查询/window 宽度）**

为可测 + 简单，列模板放内联 `:style`，窄屏堆叠用 `lg:` Tailwind 不便（动态），改用一个 `matchMedia` 响应式：

```vue
<script setup lang="ts">
/**
 * 监控页两栏壳 —— GEO 比例（左定宽 + 右自适应）固化一处；窄屏(<lg) 上下堆叠。
 * 各页只填 #left / #right 插槽。
 */
import { ref, onMounted, onBeforeUnmount, computed } from "vue";

const props = defineProps<{ leftWidth?: string; gap?: string }>();

const wide = ref(true);
let mq: MediaQueryList | null = null;
const onChange = () => { wide.value = mq?.matches ?? true; };
onMounted(() => {
  mq = window.matchMedia("(min-width: 1024px)");
  wide.value = mq.matches;
  mq.addEventListener("change", onChange);
});
onBeforeUnmount(() => mq?.removeEventListener("change", onChange));

const gridStyle = computed(() => ({
  display: "grid",
  minHeight: "0",
  flex: "1",
  gap: props.gap ?? "18px",
  gridTemplateColumns: wide.value ? `${props.leftWidth ?? "340px"} 1fr` : "1fr",
}));
</script>

<template>
  <div :style="gridStyle">
    <div class="min-h-0"><slot name="left" /></div>
    <div class="min-h-0"><slot name="right" /></div>
  </div>
</template>
```

> vitest/jsdom 里 `window.matchMedia` 默认未实现 —— 测试 setup 需 stub。在 spec 顶部加：
> ```ts
> import { beforeAll, vi } from "vitest";
> beforeAll(() => {
>   vi.stubGlobal("matchMedia", (q: string) => ({
>     matches: true, media: q, addEventListener() {}, removeEventListener() {},
>     addListener() {}, removeListener() {}, onchange: null, dispatchEvent() { return false; },
>   }));
> });
> ```
> （`wide` 初值 `true`，stub `matches:true` → 测试断言 `340px 1fr` 成立。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/ui/__tests__/SplitPane.spec.ts`
Expected: PASS（3 测试）。若失败因 matchMedia 未 stub，按 3b 注补 stub。

- [ ] **Step 5: 类型检查 + commit**

Run: `cd frontend && npx vue-tsc -b`（emit `vite.config.js` 则 `git checkout --` 还原）
```bash
git add frontend/src/components/ui/SplitPane.vue frontend/src/components/ui/__tests__/SplitPane.spec.ts
git commit -m "feat(frontend): 新增 SplitPane 两栏壳（GEO 340px 1fr 比例固化 + 窄屏堆叠）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 知乎批次聚合 KPI 纯函数

**Files:**
- Create: `frontend/src/lib/monitor-zhihu-kpi.ts`（确认 monitor-batch 实际目录后同目录放置）
- Test: `frontend/src/lib/__tests__/monitor-zhihu-kpi.spec.ts`

新增聚合 KPI 全部由现有 `TaskSnapshot.latest` 聚合得到（字段：`matched_count`、`rank`，`rank=-1` 表示未进 top-N）。抽成纯函数便于测试与右栏复用。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/lib/__tests__/monitor-zhihu-kpi.spec.ts
import { describe, it, expect } from "vitest";
import { batchZhihuKpis } from "../monitor-zhihu-kpi";

// 最小快照形状：只取聚合需要的字段
const snap = (matched_count: number, rank: number) => ({ matched_count, rank });

describe("batchZhihuKpis", () => {
  it("counts hit questions (matched_count > 0) over total", () => {
    const k = batchZhihuKpis([snap(2, 3), snap(0, -1), snap(1, 5)]);
    expect(k.total).toBe(3);
    expect(k.hitQuestions).toBe(2);
  });

  it("averages rank over ranked questions only (excludes rank<=0)", () => {
    const k = batchZhihuKpis([snap(1, 4), snap(1, 6), snap(0, -1)]);
    expect(k.avgRank).toBe(5); // (4+6)/2
  });

  it("avgRank is null when nothing is ranked", () => {
    const k = batchZhihuKpis([snap(0, -1), snap(0, -1)]);
    expect(k.avgRank).toBeNull();
  });

  it("sums own-brand hits (total matched_count)", () => {
    const k = batchZhihuKpis([snap(2, 3), snap(0, -1), snap(3, 1)]);
    expect(k.ownHits).toBe(5);
  });

  it("handles empty input", () => {
    const k = batchZhihuKpis([]);
    expect(k).toEqual({ total: 0, hitQuestions: 0, avgRank: null, ownHits: 0 });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/lib/__tests__/monitor-zhihu-kpi.spec.ts`
Expected: FAIL（import 解析失败）。

- [ ] **Step 3: 写 monitor-zhihu-kpi.ts**

```ts
/**
 * 知乎监测「批次汇总」聚合 KPI —— 全部由各问题最新快照聚合，无需后端字段。
 *   - hitQuestions: matched_count > 0 的问题数（命中问题数 X/Y 的 X）
 *   - total:        问题总数（Y）
 *   - avgRank:      已进榜问题（rank > 0）的平均最高排名；无则 null
 *   - ownHits:      所有问题 matched_count 之和（自家命中数）
 */
export interface ZhihuKpiInput {
  matched_count: number;
  rank: number;
}
export interface ZhihuBatchKpis {
  total: number;
  hitQuestions: number;
  avgRank: number | null;
  ownHits: number;
}

export function batchZhihuKpis(snapshots: ZhihuKpiInput[]): ZhihuBatchKpis {
  const total = snapshots.length;
  let hitQuestions = 0;
  let ownHits = 0;
  const ranked: number[] = [];
  for (const s of snapshots) {
    if (s.matched_count > 0) hitQuestions++;
    ownHits += s.matched_count;
    if (s.rank > 0) ranked.push(s.rank);
  }
  const avgRank =
    ranked.length > 0
      ? Math.round((ranked.reduce((a, b) => a + b, 0) / ranked.length) * 10) / 10
      : null;
  return { total, hitQuestions, avgRank, ownHits };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/lib/__tests__/monitor-zhihu-kpi.spec.ts`
Expected: PASS（5 测试）。

- [ ] **Step 5: commit**

```bash
git add frontend/src/lib/monitor-zhihu-kpi.ts frontend/src/lib/__tests__/monitor-zhihu-kpi.spec.ts
git commit -m "feat(frontend): 知乎批次聚合 KPI 纯函数（命中问题数/平均卡位/自家命中数）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 知乎页接 SplitPane + 左栏瘦身 + ⋯ 菜单

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuMonitorModule.vue`

把主两栏 grid（line ~823 `grid-cols-[1.4fr_1fr]`）换成 `<SplitPane>`；左栏 L1/L2 列表按 GEO 行模板瘦身；3 图标按钮 → `Dropdown` 的 ⋯ 菜单。**右栏内容本任务不动**（保持现有，下一 Task 重排）——先确保接壳 + 左栏不崩。

参考：GEO 行模板 `GeoTaskModule.vue:466-543`（`grid 1.5fr .9fr 1.1fr`，名+副标 / Pill / 操作）；`Dropdown.vue` 用法见下。

- [ ] **Step 1: 引入组件**

在 `<script setup>` imports 加：
```ts
import SplitPane from "@/components/ui/SplitPane.vue";
import Dropdown from "@/components/ui/Dropdown.vue";
```
（`Pill`、`Icon` 已在用。）

- [ ] **Step 2: 主布局换 SplitPane**

把 line ~823 的 `<div class="grid ... lg:grid-cols-[1.4fr_1fr]"> 左栏section 右栏section </div>` 改为：
```vue
<SplitPane>
  <template #left> <!-- 原左栏 section 内容 --> </template>
  <template #right> <!-- 原右栏 section 内容 --> </template>
</SplitPane>
```
保留两个 `<section>` 卡片本身（卡片样式不变），仅把外层 grid 容器换成 SplitPane 的具名插槽。

- [ ] **Step 3: L1 批次列表行瘦身（3 列）**

把 L1 列表（约 1036-1111）的列从 `1.7fr .6fr 1.1fr`（名/问题数/操作）改为 GEO 口径 `1.5fr .9fr 1.1fr`：
- **列1 名称+副标**：批次名（点名仍 `openBatchName=b.name` 钻入 L2）+ 副标 `{{ b.tasks.length }} 个问题 · 品牌 {{ b.tasks[0]?.config?.target_brand }}`（参考 GeoTaskModule 副标）。
- **列2 状态 Pill**：批次是否有运行中子任务 → 运行中显示进度文案，否则一个汇总状态 Pill（如「N 命中」或最近检查态）。可用 `batchZhihuKpis` 的 `hitQuestions` 给「命中 X/Y」副状态；具体文案跟随现有 statusTone/statusText 风格。
- **列3 操作 ⋯**：见 Step 5。

- [ ] **Step 4: L2 问题列表行瘦身（5 列 → 3 列）**

把 L2 列表（约 1120-1245）从 `1.6fr .7fr .7fr .7fr 1fr`（名/浏览量/卡位/变化/操作）改为 `1.5fr .9fr 1.1fr`：
- **列1 名称+副标**：问题名 + 副标把原来的次要指标降级，如 `{{ formatVisitCount(snap.question_visit_count) }} 浏览 · 卡位 {{ snap.matched_count }}`（浏览量/卡位 从独立列移到副标）。
- **列2 状态 Pill**：原「变化」列的 matched_count delta → 仍用 `Pill`（ok/warn/info），作为关键状态。
- **列3 操作 ⋯**：见 Step 5。
- 行 `@click="selectedTaskId = t.id"` 不变。

- [ ] **Step 5: 3 图标按钮 → Dropdown ⋯ 菜单**

L1 与 L2 的操作列各替换为一个 ⋯ 触发 + `Dropdown`：

L1（启动/编辑/删除）：
```vue
<Dropdown
  :items="[
    { key: 'run', label: '启动批次', icon: 'play' },
    { key: 'edit', label: '编辑批次', icon: 'edit' },
    { key: 'delete', label: '删除批次', icon: 'trash', tone: 'danger' },
  ]"
  align="right"
  @select="(k) => k === 'run' ? startBatch(b) : k === 'edit' ? editBatch(b) : deleteBatch(b)"
>
  <template #trigger>
    <button type="button" class="inline-flex h-7 w-7 items-center justify-center rounded-full" :style="{ color: 'var(--ink-3)' }"><Icon name="more" :size="15" /></button>
  </template>
</Dropdown>
```
（图标名：用现有「⋯」图标 —— 先 `rg "name=\"(more|dots|ellipsis|menu)\"" frontend/src` 确认可用名；若无水平省略号图标，用 `more`/`dots` 之一或加一个。）

L2（运行或停止/编辑/删除）：items 第一项按 `runningTaskIds[t.id]` 在「立刻监测」(`run-task`) / 「停止」(`cancel-task`) 间切；`@select` 映射到现有 emits（`run-task`/`cancel-task`/`edit-task`/`delete-task`）。

- [ ] **Step 6: 面包屑保留**

L1→L2 的返回 + 面包屑（约 884-920）已存在，保持。确认换 SplitPane 后仍在左栏 `#left` 顶部正常显示。

- [ ] **Step 7: 验证 + commit**

Run: `cd frontend && npx vue-tsc -b`（还原 vite.config.js）+ `npx vitest run`（现有测试不应回归）。
人工自查：左栏 3 列不溢出；⋯ 菜单可点；钻取/返回正常。
```bash
git add frontend/src/components/monitor/ZhihuMonitorModule.vue
git commit -m "feat(frontend): 知乎页接 SplitPane + 左栏 GEO 式瘦身（L1/L2 三列 + ⋯ 菜单）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 右栏 L1 批次汇总重排

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuMonitorModule.vue`（右栏 L1 分支，约 1248 起的 `v-else` 批次详情）

按 spec §4.3.1：**L1 批次汇总** = KPI 四联（问题数 / 目标品牌 / 命中问题数 X/Y / 平均卡位）+「问题概览」速览表 + 导出·定时。

- [ ] **Step 1: 接入聚合 KPI**

`<script setup>` 加 `import { batchZhihuKpis } from "@/lib/monitor-zhihu-kpi";`，新增 computed：
```ts
const selectedBatchKpis = computed(() => {
  const b = selectedBatch.value;
  if (!b) return null;
  const snaps = b.tasks
    .map((t) => props.taskSnapshots[t.id]?.latest)
    .filter((s): s is NonNullable<typeof s> => !!s)
    .map((s) => ({ matched_count: s.matched_count ?? 0, rank: s.rank ?? -1 }));
  return batchZhihuKpis(snaps);
});
```
（字段名以调研报告确认的 `TaskSnapshot` 为准：`matched_count` / `rank`。）

- [ ] **Step 2: KPI 四联 UI**

右栏 L1 分支顶部放一排 4 个 KPI（横向 flex/grid，参考现有 KPI 卡样式 + GEO 详情 KPI 排布）：问题数=`selectedBatchKpis.total`、目标品牌=`selectedBatchBrand`、命中问题数=`{hitQuestions}/{total}`、平均卡位=`avgRank ?? '—'`。

- [ ] **Step 3:「问题概览」速览表 + 导出/定时**

- 概览表：列出该批次每个问题一行（问题名 + 卡位 matched_count + 最高排名 rank），紧凑表格。
- 导出·定时：把现有 `exportBatchCsv` / `scheduleBatch` 两个按钮（原 1659-1687）移到此汇总区底部（功能不变）。

- [ ] **Step 4: 验证 + commit**

Run: `cd frontend && npx vue-tsc -b` + `npx vitest run`。人工自查 L1 汇总展示完整、导出/定时可用。
```bash
git add frontend/src/components/monitor/ZhihuMonitorModule.vue
git commit -m "feat(frontend): 知乎右栏 L1 批次汇总重排（KPI 四联 + 问题概览 + 导出/定时）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 右栏 L2 问题详情重排

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuMonitorModule.vue`（右栏 L2 分支，约 1429-1606）

按 spec §4.3.1：**L2 问题详情** = KPI 五联（当前卡位 / 较上次变化 / 最高排名 / 浏览量 / 自家命中数）+ 7 天卡位趋势(左) + 答案列表(右) 并排（命中自家高亮）。

- [ ] **Step 1: KPI 五联**

把现有 2 联（卡位数量 + 最高排名，约 1471-1513）扩成 5 联：
- 当前卡位 = `snap.matched_count`
- 较上次变化 = `latest.matched_count - prev.matched_count`（现 L2 列表已有此 delta 计算，复用/抽 helper）
- 最高排名 = `snap.rank`（-1 → 「未进榜」）
- 浏览量 = `formatVisitCount(snap.question_visit_count)`（从左栏迁来）
- 自家命中数 = `snap.matched_count`（spec 称「自家命中数」复用 matched_count；如与「当前卡位」重复，二者取 spec 口径：当前卡位=本次命中位置数、自家命中数=matched_count 总命中——若同值，UI 仍按 spec 五联列出，标签区分）

> 实现注：若「当前卡位」与「自家命中数」在数据上同为 `matched_count`，在 plan 执行时以 spec §4.3.1 五联标签为准呈现；如确为同值，向用户在 QA 时确认是否合并（先按五联实现，QA 决定）。

- [ ] **Step 2: 趋势(左) + 答案列表(右) 并排**

当前趋势 `LineChart`（1534-1544）与答案列表（1572-1606）是上下堆叠。改为左右并排：外层 `grid` `1fr 1.05fr`（参考 GeoKeywordDetail compete tab 的 `grid 1fr 1.05fr`），左格趋势、右格答案列表。趋势继续用 `LineChart`（`sparkChartLabels`/`sparkPoints`/`y-max=selectedTopN` 不变）；答案列表 `matches_brand` 高亮逻辑（var(--primary-soft) + 「自家」标）保留。窄屏（壳已堆叠）此处可退化为上下（用 `lg:grid-cols-[1fr_1.05fr]` 或同 matchMedia 思路）。

- [ ] **Step 3: 验证 + commit**

Run: `cd frontend && npx vue-tsc -b` + `npx vitest run`。人工自查 L2 五联 + 趋势/列表并排 + 自家高亮。
```bash
git add frontend/src/components/monitor/ZhihuMonitorModule.vue
git commit -m "feat(frontend): 知乎右栏 L2 问题详情重排（KPI 五联 + 趋势左/答案列表右并排）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 收尾验证 + push + PR

- [ ] **Step 1: 全量验证**

Run: `cd frontend && npx vue-tsc -b && npx vitest run`（0 类型错；测试全过，含 SplitPane 3 + kpi 5 新测试）。还原 vue-tsc 杂散产物。`git status --porcelain frontend/package-lock.json` 应空。

- [ ] **Step 2: push + PR**

```bash
git push -u origin claude/monitor-ux-zhihu
gh pr create --base main --title "feat(frontend): 监控页 UX 重设计 ①·知乎监测（SplitPane + 左栏瘦身 + 右栏 L1/L2 重排）" --body "见 docs/superpowers/plans/2026-06-12-monitor-ux-zhihu.md。① 四页改造的模板页：新建 SplitPane 壳、左栏 GEO 式瘦身(⋯菜单)、右栏 L1 汇总/L2 详情重排。新增聚合 KPI 全客户端、无后端改动。" --base main
```
返回 PR URL，停 pending。

- [ ] **Step 3: 用户逐页 QA（无法 headless 验证视觉）**

按 spec §12「边栏①」：dev/真机起应用 → 知乎监测页验证：(a) 左右比例=GEO（340px 1fr）且窄屏堆叠；(b) 左栏 L1/L2 瘦身后无截断/溢出、⋯ 菜单运行/编辑/删除可用、钻取/返回正常；(c) 右栏 L1 汇总四联+概览+导出/定时、L2 五联+趋势/列表并排、迁来的指标（浏览量/变化）完整无丢失、自家高亮在。

---

## Self-Review

**Spec 覆盖（§4.1/§4.2/§4.3.1）：** SplitPane 壳=Task1；左栏瘦身+⋯=Task3；L1 汇总(KPI四联+概览+导出/定时)=Task4；L2 详情(KPI五联+趋势/列表并排)=Task5。聚合 KPI 客户端=Task2（已验证字段存在、无后端改动）。✓

**Placeholder 扫描：** SplitPane 与 KPI 纯函数给了完整代码 + 测试；UI 重排任务（3/4/5）给了字段映射 + GEO 参考行号 + 数据来源 + 验收，markup 由实现者照 GEO 模板 + 现有代码落地（UI 重构按模板实现，非逐行抄）。无 TBD。

**类型/命名一致：** `batchZhihuKpis` / `ZhihuBatchKpis`（total/hitQuestions/avgRank/ownHits）在定义、测试、Task4 computed 一致。SplitPane props（leftWidth/gap）在定义、测试、用法一致。`Dropdown` items/`@select` 按调研报告确认的 API。

**风险/QA：** 纯视觉结果无法 headless 验证 → Task6 Step3 用户逐页 QA。L2「当前卡位」vs「自家命中数」可能同值 → 先按 spec 五联实现，QA 时由用户定夺是否合并（Task5 Step1 注）。`more` 图标名实现前 `rg` 确认。SplitPane 窄屏用 matchMedia（jsdom 需 stub，已在测试注明）。
