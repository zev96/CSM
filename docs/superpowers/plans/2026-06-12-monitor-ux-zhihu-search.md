# 监控页 UX 重设计 ①·第二页（知乎搜索）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把知乎搜索页（`ZhihuSearchModule.vue`, 462 行）改成 GEO 式两栏，**复用知乎监测页刚建立的模板**（`SplitPane` / `Dropdown` ⋯ / KPI 聚合 + 左右栏 L1/L2 分支模式）。这是 ① 第二页。

**Architecture:** 统一现有的两个 `grid lg:grid-cols-[1.4fr_1fr]` 块（L1 块 + L2 块）为**单个 `SplitPane`**，左栏按 `selectedId` 切 L1 任务列表 / L2 关键词列表，右栏切 L1 任务汇总 / L2 关键词详情 —— 镜像 `ZhihuMonitorModule`。知乎搜索**自包含**（无 props，自管 fetch/SSE），保持不变。新增聚合函数 `batchZhihuSearchKpis`（`batchZhihuKpis` 不可复用：需「最佳首位」= min first_rank）。

**Tech Stack:** Vue 3 `<script setup>`, Tailwind, Vitest, vue-tsc；复用 `SplitPane.vue` / `Dropdown.vue` / `LineChart.vue` / `Pill.vue`。

**设计依据:** spec §4.1/§4.2/§4.3.4。**模板参考:** `ZhihuMonitorModule.vue`（已 merge）。

## 与模板的关键差异（实现分歧点）
- **自包含**：知乎搜索无 props，自己 `loadTasks/loadLatest/loadAllTaskHistories` + SSE。不改数据层。
- **L1 = 任务**（无 batch 分组）；**L2 = 关键词**（`KeywordResult`，**只读、无操作菜单** —— L2 关键词行没有 ⋯，只是选中行）。
- **新聚合**：`batchZhihuSearchKpis`（最佳首位 = min first_rank，非平均）。
- **L2 KPI 三联**（卡位数量/最高排名/自家命中数），比知乎监测五联简单。
- **结果列表字段不同**：`title`/`author_name`/`content_type`(article→专栏/answer→回答)/`matched_field`(='fulltext'→·正文)/`matches_brand`(自家高亮)。
- **保留**：L2 左栏的 3 个 banner（error / risk_control / **fulltextNoCookie** line 349）+ breadcrumb（`backToList()` → `selectedId=null`）。
- 操作（run/stop/edit/delete）是**内部函数**（runNowTask/cancelTask/openEdit/removeTask），无 emit —— ⋯ 菜单直接调它们。
- **通用模板点**（沿用知乎页约定）：列表行加 hover 反馈（用 `@mouseenter/@mouseleave` inline-style，不用 scoped `:hover` —— 见 [[feedback_vue_inline_style_hover_clobber]]）。

---

## Task 1: `batchZhihuSearchKpis` 聚合函数

**Files:**
- Modify: `frontend/src/utils/monitor-zhihu-kpi.ts`（追加导出，与 `batchZhihuKpis` 同文件）
- Test: `frontend/src/utils/__tests__/monitor-zhihu-search-kpi.spec.ts`（新建）

- [ ] **Step 1: 写失败测试**
```ts
// frontend/src/utils/__tests__/monitor-zhihu-search-kpi.spec.ts
import { describe, it, expect } from "vitest";
import { batchZhihuSearchKpis } from "../monitor-zhihu-kpi";

const kw = (matched_count: number, first_rank: number) => ({ matched_count, first_rank });

describe("batchZhihuSearchKpis", () => {
  it("counts hit keywords (matched_count > 0) over total", () => {
    const k = batchZhihuSearchKpis([kw(2, 3), kw(0, 0), kw(1, 5)]);
    expect(k.total).toBe(3);
    expect(k.hitKeywords).toBe(2);
  });
  it("bestFirstRank is the MIN first_rank among hits (first_rank > 0)", () => {
    const k = batchZhihuSearchKpis([kw(1, 5), kw(1, 2), kw(0, 0)]);
    expect(k.bestFirstRank).toBe(2);
  });
  it("bestFirstRank is null when nothing ranked", () => {
    const k = batchZhihuSearchKpis([kw(0, 0), kw(0, 0)]);
    expect(k.bestFirstRank).toBeNull();
  });
  it("sums own-brand hits (total matched_count)", () => {
    const k = batchZhihuSearchKpis([kw(2, 3), kw(3, 1)]);
    expect(k.ownHits).toBe(5);
  });
  it("handles empty input", () => {
    expect(batchZhihuSearchKpis([])).toEqual({ total: 0, hitKeywords: 0, bestFirstRank: null, ownHits: 0 });
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — `cd frontend && npx vitest run src/utils/__tests__/monitor-zhihu-search-kpi.spec.ts` → FAIL（import 解析失败，函数未导出）。

- [ ] **Step 3: 追加到 `monitor-zhihu-kpi.ts`**（在 `batchZhihuKpis` 之后）：
```ts
/**
 * 知乎搜索「任务汇总」聚合 KPI —— 由该任务各关键词最新结果聚合。
 *   - hitKeywords:   matched_count > 0 的关键词数（命中关键词数）
 *   - total:         关键词总数
 *   - bestFirstRank: 所有命中关键词中最好的首位（min first_rank，first_rank>0）；无则 null
 *   - ownHits:       所有关键词 matched_count 之和（自家命中数）
 */
export interface ZhihuSearchKpiInput {
  matched_count: number;
  first_rank: number;
}
export interface ZhihuSearchKpis {
  total: number;
  hitKeywords: number;
  bestFirstRank: number | null;
  ownHits: number;
}

export function batchZhihuSearchKpis(keywords: ZhihuSearchKpiInput[]): ZhihuSearchKpis {
  const total = keywords.length;
  let hitKeywords = 0;
  let ownHits = 0;
  const firsts: number[] = [];
  for (const k of keywords) {
    if (k.matched_count > 0) hitKeywords++;
    ownHits += k.matched_count;
    if (k.first_rank > 0) firsts.push(k.first_rank);
  }
  const bestFirstRank = firsts.length > 0 ? Math.min(...firsts) : null;
  return { total, hitKeywords, bestFirstRank, ownHits };
}
```

- [ ] **Step 4: 跑测试确认通过**（5 测试）。

- [ ] **Step 5: vue-tsc + commit**
```bash
git add frontend/src/utils/monitor-zhihu-kpi.ts frontend/src/utils/__tests__/monitor-zhihu-search-kpi.spec.ts
git commit -m "feat(frontend): 知乎搜索任务聚合 KPI 纯函数（命中关键词数/最佳首位/自家命中数）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 接 SplitPane + 左栏瘦身（L1 任务 + L2 关键词）

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuSearchModule.vue`

把两个 `grid lg:grid-cols-[1.4fr_1fr]` 块（L1 块 ~247-330 + L2 块 ~333-458）统一成**单个 `<SplitPane>`**，左/右栏内部按 `selectedId` 切 L1/L2。本任务做**左栏 + 壳**；右栏内容先沿用现有（下一任务重排）。

参考模板：`ZhihuMonitorModule.vue` 的 `<SplitPane>` 用法（~line 850）+ L1 3 列行 + Dropdown（~1078-1143）。

- [ ] **Step 1** — imports：`import SplitPane from "@/components/ui/SplitPane.vue";` + `import Dropdown from "@/components/ui/Dropdown.vue";`（Pill/Icon/LineChart 已在）。确认 ⋯ 图标名 `more`（知乎监测在用）。

- [ ] **Step 2 — 单 SplitPane 壳。** 用一个 `<SplitPane>` 替换两个 grid 块。结构：
```
<SplitPane>
  <template #left>
    <section ...>  <!-- 左栏卡 -->
      <template v-if="selectedId === null"> L1 任务列表 </template>
      <template v-else> breadcrumb + banners + L2 关键词列表 </template>
    </section>
  </template>
  <template #right>
    <section ...>  <!-- 右栏卡（本任务沿用现有 L1预览 / L2详情，下一任务重排）-->
      <template v-if="selectedId === null"> 现有 L1 预览 </template>
      <template v-else> 现有 L2 详情 </template>
    </section>
  </template>
</SplitPane>
```
保留外层根 wrapper（flex col）。把现有 L1 块的左卡内容 + L2 块的左卡内容合到 `#left` 的 v-if/v-else；右卡内容合到 `#right`。

- [ ] **Step 3 — L1 任务行瘦身（3 列 `1.5fr .9fr 1.1fr`）。** 当前 `1.6fr .85fr .85fr 1fr`（名/变化/状态/操作，含恒为「—」的变化列）。改为：
  - Col1 名称（点击 `selectedId = t.id` 钻入 L2；行点 `previewId = t.id` 选中右栏预览 —— 镜像知乎监测 L1 的 name-link drill vs row-click select）+ 副标 `{{ t.config?.search_keywords?.length ?? 0 }} 个关键词 · 品牌 {{ t.config?.target_brand || '—' }}`。
  - Col2 状态 Pill（复用 `statusOf(t)` / 现有运行进度逻辑）。**去掉「变化」列**（恒为 —）。
  - Col3 ⋯ Dropdown：items `[{key:'run'/'stop' 按 running 切, ...},{key:'edit',icon:'edit'},{key:'delete',icon:'trash',tone:'danger'}]`，`@select` → `runNowTask(t.id)`/`cancelTask(t.id)`/`openEdit(t)`/`removeTask(t.id)`。
  - 行加 hover（`@mouseenter/@mouseleave` inline-style，仿知乎监测 L1 行）。

- [ ] **Step 4 — L2 关键词行瘦身（3 列 `1.5fr .9fr 1.1fr`，无操作列）。** 当前 `1.6fr .6fr .6fr .6fr`（关键词/卡位/首位/状态）。改为：
  - Col1 关键词名 + 副标 `卡位 {{ kw.matched_count }} · 首位 {{ kw.first_rank > 0 ? '#'+kw.first_rank : '—' }}`。
  - Col2 状态 Pill（命中/未命中/失败，复用现有逻辑）。
  - Col3 **留空或不设第三列** —— 关键词只读无操作。可用 2 列 `1.5fr .9fr`，或保持 3 列但 Col3 空（与 L1 视觉对齐，推荐 2 列更诚实）。选 2 列 `1.6fr 1fr`。
  - 行 `@click` 设 `selectedKeywordIdx`（现有选中逻辑）。行加 hover。
  - **保留** breadcrumb（back → `backToList()`）+ 3 个 banner（error / risk_control / **fulltextNoCookie** line 349）在 L2 左栏顶部。

- [ ] **Step 5 — 验证 + commit。** `cd frontend && npx vue-tsc -b`（还原 vite.config.js）+ `npx vitest run`（无回归）。自查：单 SplitPane、L1 3列+⋯、L2 关键词行简化、banner/breadcrumb 在、右栏暂沿用。
```bash
git add frontend/src/components/monitor/ZhihuSearchModule.vue
git commit -m "feat(frontend): 知乎搜索接 SplitPane + 左栏 GEO 式瘦身（L1 任务 ⋯ + L2 关键词行）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 右栏 L1 任务汇总

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuSearchModule.vue`（右栏 `selectedId === null` 分支）

按 §4.3.4：KPI 四联（关键词数 / 目标品牌 / 命中关键词数 / 最佳首位）+ 关键词速览 + 导出·定时（**无趋势**）。镜像知乎监测 L1 汇总（`ZhihuMonitorModule` ~1682-1863）。

- [ ] **Step 1 — 接入聚合 computed。** `import { batchZhihuSearchKpis } from "@/utils/monitor-zhihu-kpi";`，新增：
```ts
const previewKpis = computed(() => {
  const t = previewTask.value;
  if (!t) return null;
  const kws = (taskHistories.value[t.id]?.[0]?.metric?.keywords ?? []) as Array<{ matched_count?: number; first_rank?: number }>;
  return batchZhihuSearchKpis(kws.map((k) => ({ matched_count: k.matched_count ?? 0, first_rank: k.first_rank ?? 0 })));
});
```
> 用实现时确认的真实字段路径（调研：L1 预览数据源 = `taskHistories[t.id]?.[0]?.metric?.keywords`，元素是 `KeywordResult`）。

- [ ] **Step 2 — KPI 四联 UI**（复用知乎监测 L1 的 KPI 卡样式 `var(--card-2)`/`var(--line)`/radius12/pad12，`grid grid-cols-2 gap-3`）：关键词数=`previewTask.config.search_keywords?.length`（或 `previewKpis.total`）、目标品牌=`previewTask.config.target_brand`、命中关键词数=`{{ previewKpis?.hitKeywords ?? 0 }}/{{ previewKpis?.total ?? 0 }}`、最佳首位=`previewKpis?.bestFirstRank != null ? '#'+previewKpis.bestFirstRank : '—'`。

- [ ] **Step 3 — 关键词速览表 + 导出/定时。** 紧凑表：每关键词一行（关键词 / 卡位 matched_count / 首位 first_rank→`#N` 或 —）。导出/定时按钮（现有 `exportPreviewCsv` / `openSchedule`）放汇总区底部（功能不变）。

- [ ] **Step 4 — 验证 + commit。** vue-tsc + vitest。
```bash
git add frontend/src/components/monitor/ZhihuSearchModule.vue
git commit -m "feat(frontend): 知乎搜索右栏 L1 任务汇总（KPI 四联 + 关键词速览 + 导出/定时）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 右栏 L2 关键词详情

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuSearchModule.vue`（右栏 `selectedId !== null` 分支）

按 §4.3.4：KPI 三联（卡位数量 / 最高排名 / 自家命中数）+ 7 天趋势 + top-10 结果列表（内容类型标记 文章/回答 + 自家高亮 + 正文标）。趋势/列表可上下或并排（关键词详情数据较简，**上下堆叠即可**，不强制并排；如并排参考知乎监测 grid `1fr 1.05fr`）。

- [ ] **Step 1 — KPI 三联**（复用卡样式）：卡位数量=`currentKeyword.matched_count`、最高排名=`currentKeyword.first_rank > 0 ? '#'+first_rank : '未上榜'`、自家命中数=`currentKeyword.matched_count`（spec §4.3.4 口径；与卡位数量同源，按 spec 三联列出 —— 若同值在报告中 flag 供 QA）。当前是 2 联（卡位数量+最高排名），扩成 3 联。

- [ ] **Step 2 — 7 天趋势** 保留现有 `LineChart`（`selectedKwTrendLabels`/`selectedKwTrendData`/`hasSelectedKwTrend`），props 不变。

- [ ] **Step 3 — top-10 结果列表** 保留现有（`currentKeyword.results`）：`content_type` article→专栏 / answer→回答 标记、`matched_field==='fulltext'`→·正文 子标、`matches_brand`→自家高亮（var(--primary-soft)）。保留「启动监测」按钮（`runNowTask(selectedId)`）。

- [ ] **Step 4 — 验证 + commit。** vue-tsc + vitest。
```bash
git add frontend/src/components/monitor/ZhihuSearchModule.vue
git commit -m "feat(frontend): 知乎搜索右栏 L2 关键词详情（KPI 三联 + 趋势 + 结果列表）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 收尾验证 + push + PR

- [ ] **Step 1** — `cd frontend && npx vue-tsc -b && npx vitest run`（0 错；全过，含新 5 测试）。还原杂散产物。`git status --porcelain frontend/package-lock.json` 空。
- [ ] **Step 2 — final review**（整个 origin/main..HEAD：左→右联动、L1/L2 切换、SplitPane、与知乎监测模板一致、banner/fulltextNoCookie 保留、无回归）。
- [ ] **Step 3 — push + PR**
```bash
git push -u origin claude/monitor-ux-zhihu-search
gh pr create --base main --title "feat(frontend): 监控页 UX 重设计 ①·知乎搜索（复用模板：SplitPane + 左栏瘦身 + 右栏 L1/L2）" --body "见 docs/superpowers/plans/2026-06-12-monitor-ux-zhihu-search.md。① 第二页，复用知乎监测模板。新增 batchZhihuSearchKpis（最佳首位）。" --base main
```
返回 URL，停 pending。
- [ ] **Step 4 — 用户 QA**（§12）：左右比例/窄屏堆叠、L1 任务 ⋯、L2 关键词列表 + 3 banner + fulltextNoCookie、右栏 L1 四联+速览+导出/定时、L2 三联+趋势+结果列表（文章/回答标记/自家高亮/正文标）。

---

## Self-Review
- **§4.3.4 覆盖**：L1 四联(关键词数/目标品牌/命中关键词数/最佳首位)+速览+导出/定时=Task3；L2 三联+趋势+结果列表(类型标记/自家/正文)=Task4；fulltextNoCookie 保留=Task2/4；新聚合(最佳首位)=Task1。✓
- **复用 vs 适配**：SplitPane/Dropdown/KPI 卡样式复用模板；新聚合函数（非复用 batchZhihuKpis，因最佳首位=min）；L2 关键词只读无 ⋯（与知乎监测 L2 不同）；结果列表字段不同（title/author_name/content_type）。已在分歧点列明。
- **类型/命名**：`batchZhihuSearchKpis`/`ZhihuSearchKpis`(total/hitKeywords/bestFirstRank/ownHits) 在定义/测试/Task3 一致。
- **风险/QA**：自包含数据层不改；视觉逐页 QA；L2「卡位数量」vs「自家命中数」可能同值（同知乎监测 #1）→ flag QA；hover 用 inline-style（避 scoped :hover 冲突）。
