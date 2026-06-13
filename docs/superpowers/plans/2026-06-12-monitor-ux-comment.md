# 监控页 UX 重设计 ①·第四页（评论监测·三级·收官）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** 把评论监测页（`CommentMonitorModule.vue`, 1406 行，**三级 L1 任务→L2 视频→L3 单视频**）改成 GEO 式两栏，复用模板（`SplitPane`/`Dropdown`）。① 收官页。

**Architecture:** 单 `<SplitPane>`，三级用**已存在的两个 ref** 驱动：`selectedCommentTaskId`（null=L1 任务列表 / 非null=L2 视频列表，控 `#left`）+ `selectedVideoId`（非null=L3 详情 / null=L1或L2 留存汇总，控 `#right`）。无需新增 ref、无需新聚合函数（留存计算已内联）。告警 hero + 平台子页签按 spec/先例就位。props/emit 驱动（14 emit + `defineExpose`）全保留。

**Tech Stack:** Vue 3 `<script setup>`, Tailwind, Vitest, vue-tsc；复用 `SplitPane`/`Dropdown`/`LineChart`/`FormSelect`/`Pill`。

**设计依据:** spec §4.1/§4.2/§4.3.2。**模板参考:** `BaiduRankingPage.vue`（最近完成，含 hero 外置 + props/emit 驱动）/`ZhihuMonitorModule.vue`。

## 决策（plan 内已定，QA 可调）
- **平台子页签位置**：按 spec §4.2「保留在左栏顶部」→ 放 `#left` 顶（breadcrumb/L1 列表之上）。切平台 emit `update:commentSubtab` + 现有 watch 清两级选中（右栏回 L1 全局汇总）。
- **hero 收起**：告警 hero 加 `v-if="selectedCommentTaskId === null && commentAlerts.length"`（仅 L1 显示，对齐百度），留在 SplitPane 外页顶。
- **L3 时左列保持 L2 视频列表**（selectedVideoId 只控右列；左列只看 selectedCommentTaskId）—— 天然保留，选中视频行高亮。
- **空态**：始终渲染 SplitPane（左/右各空提示），对齐百度，不再用全宽空态。
- **留存趋势数据降级**（真实仅 prev+latest 两点，7 天轴补 null）：保留现状，不改数据逻辑。

## 三级状态映射（已存在，仅搬入插槽）
- `#left`：`v-if="selectedCommentTaskId === null"` → L1 任务列表（+平台 tabs）；`v-else` → L2 视频列表（+面包屑返回）。
- `#right`：`v-if="selectedVideo"` → L3 单视频详情；`v-else` → L1/L2 留存汇总（内部用 `selectedCommentTaskId` 区分 scope 文案/数据）。

---

## Task 1: 接 SplitPane + hero 收起 + 平台 tabs 左列顶 + 左栏瘦身

**Files:** Modify `frontend/src/components/monitor/CommentMonitorModule.vue`

把主体 raw `grid lg:grid-cols-[1.4fr_1fr]`（~806）统一成单 `<SplitPane>`；hero（~524-680）加收起条件留 SplitPane 外；平台 tabs（~682-745）移入 `#left` 顶；左栏 L1 任务行 3 列+⋯、L2 视频行瘦身+面包屑。**右栏 re-parent 进 `#right`、内容本任务不动**（下一任务对齐 §4.3.2）。

参考：`BaiduRankingPage.vue` 的 hero 外置 + SplitPane + L1 行 + ⋯ Dropdown。

- [ ] **Step 1 — imports**：加 `SplitPane`、`Dropdown`（LineChart/FormSelect/Pill/Icon 已在）。⋯ 图标 `more`。

- [ ] **Step 2 — 页结构**：根 flex-col。顺序：① 告警 hero（`v-if="selectedCommentTaskId === null && commentAlerts.length > 0"`，留 SplitPane 外）② `<SplitPane left-width="340px">`。SplitPane `#left`/`#right` 按状态切（见三级映射）。把现有左 section（L1/L2）迁 `#left`、右 section（L3/汇总）迁 `#right`，右栏内容 re-parent 不变。空态改为 SplitPane 内左/右空提示（不再全宽 `v-if commentRows.length===0` 覆盖整页）。

- [ ] **Step 3 — 平台子页签移入 `#left` 顶**：把现有平台 tabs（B站/抖音/快手 pills，emit `update:commentSubtab`）移到 `#left` 的最顶部（L1 任务列表之上；L2 时仍在顶，或仅 L1 显示——简单起见始终在 `#left` 顶）。「批量导入」按钮（emit `import-batch`）一并放 `#left` header（与「新增」`add-task` 同行）。切换行为/emit 不变。

- [ ] **Step 4 — L1 任务行 3 列** `1.5fr .9fr 1.1fr`（去掉「变化」列）：Col1 任务名（点击 `openCommentDetail(t.id)` 钻 L2）+ 副标（留存 `retained/total` · 平台/品牌）；Col2 状态 Pill（复用现有 status/进度）；Col3 ⋯ Dropdown：run/stop→`emit('run-batch'/'cancel-batch', t.id)`、edit→`emit('edit-batch', t.id)`、delete(danger)→`emit('delete-batch', t.id)`。行 hover（@mouseenter/leave inline）。

- [ ] **Step 5 — L2 视频行**（瘦身，只读无⋯）：保留现有列（视频名 / 评论排名 / 状态）或收成 名+副标(排名·状态)/状态 Pill；行点 `selectVideo(v.id)`，选中高亮（`selectedVideoId===v.id`）；运行进度条保留。L2 `#left` 顶加面包屑（← `backToCommentList()` + 任务名 + 视频数徽章）。hover。

- [ ] **Step 6 — 验证 + commit**：`cd frontend && npx vue-tsc -b`（还原 vite.config.js）+ `npx vitest run`（136 pass；"localStorage is not defined"=跑法错，以 vue-tsc 为准）。自查：单 SplitPane；hero 外置+收起；平台 tabs 在 `#left` 顶；L1 3列+⋯（emit 对）；L2 视频列表+面包屑；右栏 re-parent 不变；14 emit + `defineExpose` 未动；`selectedCommentTaskId`/`selectedVideoId`/`openCommentDetail`/`selectVideo`/`backToCommentList`/`closeVideoDetail` 语义不变。
```bash
git add frontend/src/components/monitor/CommentMonitorModule.vue
git commit -m "feat(frontend): 评论监测接 SplitPane + hero 收起 + 平台 tabs 左列顶 + 左栏三级瘦身（L1 ⋯ + L2 视频）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

## Discipline（Task 1）
- 右栏内容本任务 re-parent only（下一任务对齐 §4.3.2）。KEEP props/emit/expose 驱动（不改自包含）。所有现有导航 ref/fn 语义不变。三级靠现有两个 ref（不新增）。
- 若有歧义 STOP report。

---

## Task 2: 右栏 §4.3.2 对齐（L3 详情 + L1/L2 留存汇总）

**Files:** Modify `frontend/src/components/monitor/CommentMonitorModule.vue`（`#right` 内容）

右栏内容已基本符合 §4.3.2，本任务做**视觉统一 + 文案对齐**，不改数据/操作逻辑。

- [ ] **Step 1 — L3 单视频详情**（`v-if="selectedVideo"`）：KPI 三联（评论排名 `selectedVideo.rank`→`#N`/「无」、状态 Pill、总评论数 `selectedVideo.totalComments`）统一到模板卡样式（`var(--card-2)`/`var(--line)`/radius12/pad12，`grid grid-cols-3`）。保留「我的评论原文」box（按状态着色）+ 操作（打开视频链接 / 立刻监测 `emit('run-now', ...)` / 补发评论 `emit('alert-action','repost')`）。**不加抢占者列表**（已无，确认）。标题正名（如「单视频详情」）。

- [ ] **Step 2 — L1/L2 留存汇总**（`v-else`）：留存率趋势 `LineChart`（`retentionPoints`，7 天轴）+ 被删/折叠评论列表（`deletedComments`，内部滚动）保留。标题随 scope：`selectedCommentTaskId ? '任务留存汇总' : '全部留存汇总'`。L2（`v-if="selectedCommentTaskId"`）的启停/频率控件（`toggleMonitor`/`changeSchedule` + FormSelect）+「选视频看详情」提示保留。

- [ ] **Step 3 — 验证 + commit**：vue-tsc + vitest（136）。自查：只 `#right` 改；左栏 + hero/tabs 未动；emit/数据逻辑不变；KPI 卡样式与其他页一致。
```bash
git add frontend/src/components/monitor/CommentMonitorModule.vue
git commit -m "feat(frontend): 评论监测右栏对齐 §4.3.2（L3 KPI 三联统一卡样式 + L1/L2 留存汇总文案）" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 收尾 + final review + PR

- [ ] **Step 1** — 全量 `cd frontend && npx vue-tsc -b && npx vitest run`（0；136）。还原杂散产物。lockfile 空。commit plan（`docs/.../2026-06-12-monitor-ux-comment.md`）。清理任何 subagent 误建垃圾（`git status` 看 untracked，删非预期文件/root node_modules，**勿删 frontend/node_modules**）。
- [ ] **Step 2 — final review**（origin/main..HEAD：三级联动 L1/L2/L3 状态机连贯无空白、hero 外置+收起、平台 tabs 左列顶、L3 详情/汇总对齐 §4.3.2、emit/expose/导航 fn 保留、无回归）。
- [ ] **Step 3 — push + PR**
```bash
git push -u origin claude/monitor-ux-comment
gh pr create --base main --title "feat(frontend): 监控页 UX 重设计 ①·评论监测（三级 SplitPane + hero + 平台 tabs）——① 收官" --body "见 docs/superpowers/plans/2026-06-12-monitor-ux-comment.md。① 第四页（收官）。三级 L1/L2/L3 复用两 ref 映射 SplitPane。无新聚合（留存内联）。" --base main
```
返回 URL 停 pending。
- [ ] **Step 4 — 用户 QA**：比例/窄屏、告警 hero(L1)、平台 tabs(左列顶)切换、L1 任务 ⋯(run/edit/delete)+批量导入/新增、钻 L2 视频列表+面包屑、选视频→L3（KPI 三联+我的评论原文+操作）、未选→留存汇总（趋势+被删列表，L2 含启停/频率）。

---

## Self-Review
- §4.3.2 覆盖：右栏规则(selectedVideo 切)、L1 全局汇总、L2 任务汇总+启停/频率、L3 三联+原文+操作(无抢占者)=Task2；左栏三级+平台 tabs+hero=Task1。✓
- 三级状态：用现有 `selectedCommentTaskId`+`selectedVideoId`（不新增 ref），映射 SplitPane 左/右切换。无 brainstorm 需要（调研确认状态已存在 + §4.3.2 明确）。
- 决策：平台 tabs 左列顶(spec §4.2)、hero 收起(对齐百度)、空态 SplitPane 内、趋势降级保留 —— 均 plan 内已定，QA 可调。
- 复用：SplitPane/Dropdown/LineChart/FormSelect；**无新聚合函数**（留存计算内联）。
- 保留：props/emit(14)+expose、导航 fn、平台切换 watch、运行进度、监控态 ref。
- 风险/QA：视觉逐页 QA；三级联动（drill/back/select/close video）；KPI 不设重复卡（沿用既定 QA）。
