# 监控页 UX 重设计 ①·第三页（百度排名）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** 把百度排名页（`BaiduRankingPage.vue`, 1845 行）改成 GEO 式两栏，复用知乎模板（`SplitPane`/`Dropdown`/KPI 聚合），同时处理百度特有点：**props/emit 驱动**、**默认+资讯两榜并排**、**告警 hero 卡**、**riskControlMeta 风控提示**、**L1 14 天趋势**。① 第三页。

**Architecture:** 单 `<SplitPane>`（左右栏按 `selectedId` 切 L1/L2），但**告警 hero 卡留在 SplitPane 之外的页顶**（百度独有）。百度**保留 emit**（add-task/batch-import/edit-task）+ `defineExpose({reload, selectTask})` —— 不改自包含。新增 `batchBaiduKpis`（含资讯命中，`batchZhihuSearchKpis` 会漏算资讯）。L2 两榜从竖堆叠改 `grid-cols-2` 并排（资讯榜蓝框，仅 `news_present`）。

**Tech Stack:** Vue 3 `<script setup>`, Tailwind, Vitest, vue-tsc；复用 `SplitPane`/`Dropdown`/`LineChart`/`Pill`。

**设计依据:** spec §4.1/§4.2/§4.3.3。**模板参考:** `ZhihuSearchModule.vue`（最接近，已 merge）。

## 百度特有 divergence（务必处理）
- **D1 props/emit**：保留 `emit('add-task')`/`emit('batch-import')`/`emit('edit-task', t)` + `defineExpose({reload: loadTasks, selectTask})`。⋯ 菜单的 edit → `emit('edit-task', t)`（不像知乎那样开本地 modal）。L1 左卡 header 的「批量导入」「新增」按钮保留（emit）。
- **D2 两榜并排**：L2 右当前默认榜(橙 `var(--primary)`)+资讯榜(蓝 `#4f7cff`)竖堆叠 → 改 `grid-cols-2` 并排；资讯列 `v-if="currentKeyword.news_present"`；蓝框样式保留（`rgba(79,124,255,...)`）。窄屏（壳已堆叠）可退化单列。
- **D3 riskControlMeta**：L2 左卡面包屑下方的风控提示（`layer==='auth'`红/否则橙）必须原样保留。
- **D4 L1 右 14 天趋势**：L1 右卡的「理想卡位关键词数」14 天 `LineChart`（`previewChartLabels`/`previewChartSeries`）保留（知乎 L1 无趋势，百度有）。
- **D11 告警 hero**：L1 顶部全宽黑底告警 hero（`v-if="currentBaiduAlert"`）留在 SplitPane **外**的页顶（仅 L1 时显示，即 `selectedId===null`）。
- **D10 L2 趋势改语义**：L2 右当前是「理想卡位关键词数」趋势 → 改为**按选中关键词**的 14 天卡位趋势（新 computed，类似知乎搜索 `selectedKwTrend`，按 `currentKeyword.keyword` 从 `taskHistories` 每天取该关键词 `default_matched_count`）。
- **D14 启动监测单关键词**：L2 「启动监测」按钮保留 `runNow()`（只跑当前关键词，带 `?keyword=`），不要换成跑整任务。
- **D13 keywordRows**：L2 关键词列表用现有 `keywordRows`（config 为基准 + metric 合并，含未跑关键词），不要换成 `latestMetric.keywords`。

---

## Task 1: `batchBaiduKpis` 聚合函数

**Files:** Modify `frontend/src/utils/monitor-zhihu-kpi.ts`（追加，与现有聚合同文件）；Test `frontend/src/utils/__tests__/monitor-baidu-kpi.spec.ts`

- [ ] **Step 1: 失败测试**
```ts
// frontend/src/utils/__tests__/monitor-baidu-kpi.spec.ts
import { describe, it, expect } from "vitest";
import { batchBaiduKpis } from "../monitor-zhihu-kpi";

const kw = (default_matched_count: number, default_first_rank: number, news_matched_count = 0) =>
  ({ default_matched_count, default_first_rank, news_matched_count });

describe("batchBaiduKpis", () => {
  it("counts hit keywords (default OR news matched > 0) over total", () => {
    const k = batchBaiduKpis([kw(2, 3), kw(0, 0, 1), kw(0, 0, 0)]);
    expect(k.total).toBe(3);
    expect(k.hitKeywords).toBe(2); // #1 default hit, #2 news hit, #3 none
  });
  it("bestDefaultRank = MIN default_first_rank among >0", () => {
    const k = batchBaiduKpis([kw(1, 5), kw(1, 2), kw(0, 0)]);
    expect(k.bestDefaultRank).toBe(2);
  });
  it("bestDefaultRank null when none ranked", () => {
    expect(batchBaiduKpis([kw(0, 0), kw(0, 0, 2)]).bestDefaultRank).toBeNull();
  });
  it("ownHits sums default + news matched", () => {
    const k = batchBaiduKpis([kw(2, 1, 1), kw(3, 2, 0)]);
    expect(k.ownHits).toBe(6); // 2+1 + 3+0
  });
  it("handles empty", () => {
    expect(batchBaiduKpis([])).toEqual({ total: 0, hitKeywords: 0, bestDefaultRank: null, ownHits: 0 });
  });
});
```

- [ ] **Step 2: 跑确认失败** — `cd frontend && npx vitest run src/utils/__tests__/monitor-baidu-kpi.spec.ts`。

- [ ] **Step 3: 追加到 `monitor-zhihu-kpi.ts`**（勿动现有函数）:
```ts
/**
 * 百度排名「任务汇总」聚合 KPI —— 默认搜索 + 最新资讯双榜。
 *   - hitKeywords: 默认或资讯任一命中(>0)的关键词数
 *   - bestDefaultRank: 默认榜最佳首位(min default_first_rank>0)；无则 null
 *   - ownHits: 所有关键词 default_matched_count + news_matched_count 之和
 * 注：news_matched_count 由调用方从 news_results.filter(r=>r.matches_brand).length 派生
 *     （news_present=false 时传 0）。
 */
export interface BaiduKpiInput {
  default_matched_count: number;
  default_first_rank: number;
  news_matched_count: number;
}
export interface BaiduBatchKpis {
  total: number;
  hitKeywords: number;
  bestDefaultRank: number | null;
  ownHits: number;
}
export function batchBaiduKpis(keywords: BaiduKpiInput[]): BaiduBatchKpis {
  const total = keywords.length;
  let hitKeywords = 0;
  let ownHits = 0;
  const defaults: number[] = [];
  for (const k of keywords) {
    if (k.default_matched_count > 0 || k.news_matched_count > 0) hitKeywords++;
    ownHits += k.default_matched_count + k.news_matched_count;
    if (k.default_first_rank > 0) defaults.push(k.default_first_rank);
  }
  const bestDefaultRank = defaults.length > 0 ? Math.min(...defaults) : null;
  return { total, hitKeywords, bestDefaultRank, ownHits };
}
```

- [ ] **Step 4: 跑确认通过**（5 测试）。
- [ ] **Step 5: vue-tsc + commit**
```bash
git add frontend/src/utils/monitor-zhihu-kpi.ts frontend/src/utils/__tests__/monitor-baidu-kpi.spec.ts
git commit -m "feat(frontend): 百度排名任务聚合 KPI 纯函数（命中关键词数/最佳排名/含资讯命中）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 接 SplitPane + 告警 hero 外置 + 左栏瘦身

**Files:** Modify `frontend/src/components/monitor/history/BaiduRankingPage.vue`

把两套 `grid lg:grid-cols-[1.4fr_1fr]` 块（L1 ~1085 / L2 ~1417）统一成单 `<SplitPane>`；**告警 hero（~951-1083）留在 SplitPane 外页顶**（`selectedId===null` 时显示）；左栏 L1 任务 3 列+⋯（emit 保留）、L2 关键词 2 列只读；保留 breadcrumb + riskControlMeta。右栏本任务沿用现有（下一任务重排）。

参考：`ZhihuSearchModule.vue` SplitPane(256-578)、L1 行+Dropdown(282-335)、L2 行(363-381)、面包屑(342-349)。

- [ ] **Step 1** — imports：`SplitPane`、`Dropdown`（Pill/Icon/LineChart 已在）。⋯ 图标 `more`。
- [ ] **Step 2 — 页结构**：根 flex-col。`selectedId===null` 时先渲染告警 hero（现有 ~951-1083，原样），其下放 `<SplitPane>`；`selectedId!==null` 时不渲染 hero、直接 SplitPane。SplitPane 的 `#left`/`#right` 各 `v-if="selectedId===null"`/`v-else`。把现有 L1 左卡内容 → `#left` v-if、L2 左卡 → `#left` v-else；L1 右卡 → `#right` v-if、L2 右卡 → `#right` v-else（右卡内容本任务不动，仅 re-parent）。
- [ ] **Step 3 — L1 左卡 header 按钮保留**：「批量导入」(`emit('batch-import')`) +「新增」(`emit('add-task')`) 按钮移到 `#left` 的 L1 header 区（emit 不变）。
- [ ] **Step 4 — L1 任务行 3 列** `1.5fr .9fr 1.1fr`（删「变化」列）：Col1 名(点击 `enterDetail(t.id)`)+副标(`t.config.search_keywords?.length` 个关键词 · 品牌)；Col2 状态 Pill（复用现有 status/进度）；Col3 ⋯ Dropdown：run/stop→`runNowTask(t.id)`/`cancelTask(t.id)`、edit→`emit('edit-task', t)`、delete(danger)→`deleteTask(t)`。行 hover（@mouseenter/leave inline）。
- [ ] **Step 5 — L2 关键词行 2 列** `1.6fr 1fr`（只读无⋯）：Col1 关键词+副标(默认卡位 `default_matched_count` · 首位 `default_first_rank>0?'#'+:'—'`)；Col2 状态 Pill。行点 `selectedKeywordIdx`（现有）。hover。**保留**面包屑(back→`backToList()`)+关键词数徽章+`riskControlMeta` 提示（原样，在 L2 `#left` 顶）。
- [ ] **Step 6 — 验证 + commit**：`cd frontend && npx vue-tsc -b`(还原 vite.config.js)+`npx vitest run`。自查：单 SplitPane、hero 外置仅 L1、L1 3列+⋯(emit 对)、L2 2列、riskControlMeta/面包屑在、右栏沿用、`defineExpose`/`defineEmits` 未动。
```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue
git commit -m "feat(frontend): 百度排名接 SplitPane + 告警 hero 外置 + 左栏 GEO 瘦身（L1 ⋯ + L2 关键词）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 右栏 L1 任务汇总

**Files:** Modify `BaiduRankingPage.vue`（右栏 `selectedId===null` 分支）

按 §4.3.3：KPI 四联（关键词数/目标品牌/命中关键词数/最佳排名）+ **14 天趋势保留** + 关键词速览 + 导出/定时。

- [ ] **Step 1 — KPI computed**：`import { batchBaiduKpis } from "@/utils/monitor-zhihu-kpi";`
```ts
const previewKpis = computed(() => {
  const t = previewTask.value;
  if (!t) return null;
  const kws = (taskHistories.value[t.id]?.[0]?.metric?.keywords ?? []) as any[];
  return batchBaiduKpis(kws.map((k) => ({
    default_matched_count: k.default_matched_count ?? 0,
    default_first_rank: k.default_first_rank ?? 0,
    news_matched_count: (k.news_results ?? []).filter((r: any) => r.matches_brand).length,
  })));
});
```
> 用实现时确认的真实 `previewTask`/`taskHistories` 字段路径。
- [ ] **Step 2 — KPI 四联**（复用知乎卡样式 `var(--card-2)`/`var(--line)`/radius12/pad12，`grid grid-cols-2 gap-3`）：关键词数=`previewTask.config?.search_keywords?.length`、目标品牌=`previewTask.config?.target_brand||'—'`、命中关键词数=`{{previewKpis?.hitKeywords??0}}/{{previewKpis?.total??0}}`、最佳排名=`previewKpis?.bestDefaultRank!=null?'#'+previewKpis.bestDefaultRank:'—'`。
- [ ] **Step 3 — 14 天趋势保留 + 速览 + 导出/定时**：保留现有 L1「理想卡位关键词数」`LineChart`（`previewChartLabels`/`previewChartSeries`，props 不变）放 KPI 下方。加关键词速览表（关键词/默认卡位 `default_matched_count`/默认首位 `default_first_rank`）。导出(`exportPreviewCsv`)/定时(`openScheduleEditor`→emit edit-task) 按钮放底部（不变）。
- [ ] **Step 4 — 验证 + commit**：vue-tsc + vitest。
```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue
git commit -m "feat(frontend): 百度排名右栏 L1 任务汇总（KPI 四联 + 14天趋势 + 关键词速览 + 导出/定时）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 右栏 L2 关键词详情（两榜并排 + 趋势改语义）

**Files:** Modify `BaiduRankingPage.vue`（右栏 `selectedId!==null` 分支）

按 §4.3.3：KPI 三联（默认搜索卡位/最新资讯卡位/最佳排名）+ 14 天趋势（**改按选中关键词**）+ **默认+资讯两榜并排**（资讯蓝框，仅 news_present）+ 启动监测（单关键词保留）。

- [ ] **Step 1 — L2 选中关键词趋势 computed（D10）**：新增（镜像知乎搜索 `selectedKwTrend`，14 天，按 `currentKeyword.keyword` 从 `taskResults`/`taskHistories` 每天取该关键词 `default_matched_count`）：
```ts
const selectedKwTrend = computed<Array<{ iso: string; label: string; v: number | null }>>(() => {
  const out: Array<{ iso: string; label: string; v: number | null }> = [];
  const now = new Date();
  for (let i = 13; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    out.push({ iso, label: String(d.getDate()), v: null });
  }
  const name = currentKeyword.value?.keyword;
  if (!name) return out;
  const seen = new Set<string>();
  for (const r of (taskResults.value ?? [])) {
    const d = new Date(r.checked_at); if (Number.isNaN(d.getTime())) continue;
    const iso = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    if (seen.has(iso)) continue;
    const b = out.find((x) => x.iso === iso);
    if (b) { const kw = (r.metric?.keywords ?? []).find((k: any) => k.keyword === name); b.v = kw ? Number(kw.default_matched_count)||0 : 0; seen.add(iso); }
  }
  return out;
});
const selectedKwTrendLabels = computed(() => selectedKwTrend.value.map((b) => b.label));
const selectedKwTrendData = computed(() => selectedKwTrend.value.map((b) => b.v));
const hasSelectedKwTrend = computed(() => selectedKwTrend.value.some((b) => b.v !== null));
```
> 确认 L2 选中任务的历史源（百度 L2 用 `taskResults`/`loadHistory` 装的 30 条；按文件实际命名调整）。
- [ ] **Step 2 — KPI 三联**（复用卡样式，`grid grid-cols-3`）：默认搜索卡位=`currentKeyword.default_matched_count`；最新资讯卡位=`(currentKeyword.news_results??[]).filter(r=>r.matches_brand).length`（无资讯/`!news_present` 显 `—`）；最佳排名=两榜 `>0` 首位最小值 `Math.min(...[default_first_rank, news_first_rank].filter(x=>x>0))`（无则「未上榜」）。
- [ ] **Step 3 — 14 天趋势**：把 L2 右的 `LineChart` 数据源换成 Step 1 的 `selectedKwTrendLabels`/`selectedKwTrendData`（`hasSelectedKwTrend` 守卫），label「卡位数量」。
- [ ] **Step 4 — 两榜并排（D2）**：把竖堆叠的默认榜(橙 border)+资讯榜(蓝 border)包进 `grid` `gridTemplateColumns: news_present ? '1fr 1fr' : '1fr'`；左默认榜(`default_results`)、右资讯榜(`news_results`，`v-if="currentKeyword.news_present"`，蓝框 `#4f7cff`/`rgba(79,124,255,...)`)。`matches_brand` 高亮保留（默认橙、资讯蓝）。窄屏退化单列。
- [ ] **Step 5 — 启动监测保留**：底部「启动监测」按钮保留现有 `runNow()`（单关键词）。
- [ ] **Step 6 — 验证 + commit**：vue-tsc + vitest。
```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue
git commit -m "feat(frontend): 百度排名右栏 L2 详情（KPI 三联 + 选中关键词趋势 + 默认/资讯两榜并排）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 收尾 + final review + PR

- [ ] **Step 1** — `cd frontend && npx vue-tsc -b && npx vitest run`（0；全过含新 5 测试）。还原杂散产物。lockfile 空。commit plan（`docs/.../2026-06-12-monitor-ux-baidu.md`）。
- [ ] **Step 2 — final review**（origin/main..HEAD：左→右联动、hero 外置仅 L1、两榜并排+news 门控、riskControlMeta/14天趋势/emit/expose 保留、L2 趋势按关键词、与模板一致、无回归）。
- [ ] **Step 3 — push + PR**
```bash
git push -u origin claude/monitor-ux-baidu
gh pr create --base main --title "feat(frontend): 监控页 UX 重设计 ①·百度排名（SplitPane + 两榜并排 + 告警 hero 外置）" --body "见 docs/superpowers/plans/2026-06-12-monitor-ux-baidu.md。① 第三页。复用模板 + 百度特有(两榜/hero/风控/emit)。新增 batchBaiduKpis。" --base main
```
返回 URL 停 pending。
- [ ] **Step 4 — 用户 QA**：比例/窄屏、告警 hero(L1)、L1 ⋯(批量导入/新增/run/edit/delete)、L2 关键词列表+riskControlMeta、右栏 L1 四联+14天趋势+速览+导出/定时、L2 三联+按关键词趋势+**两榜并排(资讯蓝框仅 news_present)**+启动监测。

---

## Self-Review
- §4.3.3 覆盖：L1 四联+14天趋势+速览+导出/定时=Task3；L2 三联+趋势+两榜并排=Task4；新聚合=Task1；接壳+hero+左栏=Task2。✓
- divergence 处理：D1 emit/expose 保留(Task2)、D2 两榜并排(Task4)、D3 riskControlMeta(Task2)、D4 L1 趋势保留(Task3)、D10 L2 趋势改语义(Task4 Step1)、D11 hero 外置(Task2)、D12 新聚合(Task1)、D13 keywordRows 保留(Task2)、D14 单关键词启动(Task4)。✓
- 类型/命名：`batchBaiduKpis`/`BaiduBatchKpis`(total/hitKeywords/bestDefaultRank/ownHits) 在定义/测试/Task3 一致。
- 风险/QA：视觉逐页 QA；百度 props/emit 驱动别误改自包含；两榜 news_present 门控；L2 历史源命名实现时确认；KPI 不设重复卡（沿用既定 QA）。
