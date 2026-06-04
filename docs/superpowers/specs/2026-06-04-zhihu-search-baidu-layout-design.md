# 知乎搜索监控对齐百度排名两级布局 — 设计

- 日期：2026-06-04
- 范围：前端单文件 `frontend/src/components/monitor/ZhihuSearchModule.vue` 重排
- 状态：待用户 review

## 背景与目标

监测中心各 tab 布局应一致。「百度排名」（`history/BaiduRankingPage.vue`）是已验证的成熟模式——
**两级双卡**布局；而「知乎搜索」（`ZhihuSearchModule.vue`）仍是单级（窄任务列表 + 右侧把所有
关键词结果纵向堆叠）。本设计把知乎搜索改为与百度一致的两级双卡布局。

**已确认的决策（来自 brainstorming 问答）**：

1. 现在就做完整两级对齐（用户知悉 B+C UI 大改将至、IA 改动可能被冲掉，仍选择现在做：百度两级是
   成熟模式，B+C 大概率收敛到它，对齐不浪费）。
2. 范围＝核心两级 + 导出/定时监测。**不做**告警 hero、批量导入。
3. L2「启动监测」跑整个任务（知乎关键词少、跑全部快），复用现有 `run-now`，**纯前端、不改 sidecar**。

## 现状 vs 目标

**现状（单级）**：`<div flex gap-4>` — 左 240px 任务列表；右详情区＝任务头 + 状态提示 + 近 7 天
趋势卡 + `v-for keywordResults` 每关键词一张结果表，全部纵向堆叠。无钻取。

**目标（两级，镜像百度）**：
- **L1（`selectedId === null`）**：grid `[1.4fr_1fr]`，左「监测任务」表 + 右「任务详情」预览卡。
- **L2（`selectedId !== null`）**：grid `[1.4fr_1fr]`，左「关键词列表」+ 右「单关键词详情」。

## 架构决策

**镜像 BaiduRankingPage 的两级结构进 `ZhihuSearchModule.vue`，保持独立组件，纯前端。**

理由：现有每个监测模块都是独立组件（`ZhihuMonitorModule` / `CommentMonitorModule` /
`BaiduRankingPage` 各自实现，无共享布局组件）。镜像符合既有模式，改动锁在一个文件，风险最低，
B+C 大改时连带替换也只动一处。

**否决方案**：抽通用 `<MonitorWorkbench>` 共享组件。百度（双榜/卡位率）与知乎（命中/排名/正文匹配）
数据模型差异大，通用化需大量 slot/props，过度抽象；且 B+C 要重做 IA，现在抽的组件大概率被推翻。

## L1 落地页设计（`selectedId === null`）

grid `lg:grid-cols-[1.4fr_1fr]`，两 `<section>` 卡片（`var(--card)` / `var(--radius-card)` / padding 22px）。

### 左卡「监测任务」
- header：标题 `监测任务` + 右上 `新增任务` 按钮（橙底）。**无批量导入**。
- 列头（滚动区外，`flex-shrink-0`）：`任务名字 / 变化 / 状态 / 操作`，grid `1.6fr .85fr .85fr 1fr`。
- 数据行：
  - 任务名（`var(--primary-deep)`，点击 = `enterDetail(t.id)` 进 L2）+ 副行 `N 个关键词 · 品牌 X`。
  - 变化：暂统一 `—`（与百度 L1 一致）。
  - 状态：跑动中显示 `current/total` + 进度条（复用 `monitorStatus.taskProgress`）；空闲显示状态 Pill
    （见下「状态算法」）。
  - 操作：▶立刻监测（`runNow(t.id)` 跑整任务）/ ✎编辑 / 🗑删除；跑动中 ▶→⏹（`monitorStatus.cancel`）。
- hover/点击行 → `previewId = t.id`（右卡预览定位），默认第一条。

### 右卡「任务详情」预览
- 标题 = `previewTask.name` + 副标题 `任务详情`。
- 属性：
  - `目标品牌`：`previewTask.config.target_brand || '—'`。
  - `近 7 天趋势`：复用现有 `trendBuckets`（命中关键词数 + 最优排名双线，`LineChart`）。**保留 7 天**，
    不改 14 天（已对齐 `ZhihuMonitorModule`，排名哨兵 15）。数据点 < 2 给文字占位。
- 底部固定（`flex-shrink-0`）：`导出数据`（新增，见下）/ `定时监测`（复用 `openEdit`，进编辑弹窗调
  `schedule_cron`）。

## L2 二级关键词设计（`selectedId !== null`）

grid `lg:grid-cols-[1.4fr_1fr]`。

### 左卡「关键词列表」
- header：返回箭头（`backToList()`）+ `知乎搜索 · 关键词列表` + 任务名 + `N 个关键词`徽章。
- **知乎特有状态条**（移到此处，原在单级详情顶部）：
  - `error` → `鉴权失败`（检查知乎 Access Secret / 系统时钟）。
  - `risk_control` → `频率限制`（30001，稍后重试）。
  - `fulltextNoCookie` → `全文匹配未生效`（已开全文匹配但未配知乎 Cookie，去 Cookie 管理）。
- 列头：`关键词 / 命中数 / 首位排名 / 状态`，grid `1.6fr .6fr .6fr .6fr`。
- 数据行（点击选 `selectedKeywordIdx`）：
  - 关键词名。
  - 命中数 = `kw.matched_count`。
  - 首位排名 = `kw.first_rank > 0 ? '#'+first_rank : '—'`。
  - 状态 Pill：`first_rank > 0` → `命中`(ok)；`前 10 无命中` → `未命中`(info)；`fetch_error` → `失败`(alert)。

### 右卡「单关键词详情」
- header：`关键词详情` + 选中关键词名。
- KPI 二联（替代百度双卡位）：`命中条数 = matched_count` / `首位排名 = first_rank`（无命中显示 `—`）。
- 选中关键词结果表＝**知乎现有那张表**：列 `# / 标题 / 类型 / 作者 / 赞同`；命中行底色 `var(--primary-soft)`；
  标题后 `命中:{matched_brand}({matched_field})`，且 `matched_field==='fulltext'` 追加 **「· 正文」**；
  `empty_reason` / `fetch_error` 行内提示。标题链接到 `r.url`。
- 底部固定：`▶ 启动监测`（`runNow(selectedId)` 跑整任务，复用现有接口；跑动中禁用显示「监测中…」）。
- 趋势不在 L2 重复（L1 预览卡已有同一份任务级 7 天趋势）；如需与百度完全一致再补，属可选项。

## 数据模型映射

知乎 `KeywordResult { keyword, results[], matched_count, first_rank, result_count, empty_reason,
api_code, fetch_error }`；`ResultItem { rank, title, content_type, url, voteup_count, author_name,
matches_brand, matched_brand, matched_field, fulltext_status, excerpt }`。**数据形状不变**，仅前端重排。

相对百度的简化（知乎无此概念）：去掉双榜（default/news）、`ideal_rank` 卡位率、告警 hero、批量导入。

## 状态算法（L1 状态列）

基于该任务最新一份 result：
- 任一关键词 `first_rank > 0` → `正常`(ok)。
- 全部关键词前 10 无命中 → `未命中`(info)。
- `status==='error'` → `鉴权失败`(alert)；`status==='risk_control'` → `频率限制`(warn)。
- 无历史 → `未跑`(info)。

## 实现要点（script 改动）

复用现有 `loadTasks` / `loadLatest` / `runNow` / `removeTask` / SSE 订阅 / `trendBuckets`。新增：

- `previewId` + `previewTask`（L1 右卡预览，默认第一条）。
- `selectedKeywordIdx` + `currentKeyword`（L2 选中关键词）。
- `enterDetail(id)`（load 后切 `selectedId`）/ `backToList()`（清 `selectedId` + `selectedKeywordIdx`）。
- `taskHistories` 每任务历史 fan-out（L1 状态列 + 预览卡趋势需要跨任务历史；参照百度
  `loadAllTaskHistories`，对 `/api/monitor/results?task_id&limit` 并行拉）。
- `exportPreviewCsv()`：导出预览任务各关键词「命中条数」CSV（BOM + UTF-8，参照百度）。
- 状态算法 helper。
- 进入 L2 自动选第一个关键词（`watch keywordResults`）。

template 由单级 `flex gap-4` 改为 `v-if selectedId===null` 两级双卡。复用现成 `Pill / Icon / LineChart /
AddTaskModal`（`AddTaskModal` 保持组件内自包含，不改成 MonitorView 事件模式——范围不含批量导入，
最小改动）。

## 影响面 / 非目标

- **影响面**：单文件 `ZhihuSearchModule.vue`（script 增量 + template 重写）。纯前端，vite 热更可见，
  **不重启 sidecar**。`MonitorView.vue` 的 `<ZhihuSearchModule />` 挂载不变。
- **非目标（YAGNI）**：告警 hero、批量导入、双榜、卡位率、L2 单关键词跑、共享布局组件、后端改动。

## 测试 / 验证

- 单测：知乎搜索无独立组件单测惯例（现有 `ZhihuSearchModule` 也无）；逻辑 helper（状态算法）可加轻量
  vitest。主要靠 browser-dev 手测。
- 手测路径（browser-dev http://localhost:5173 → 监测中心 → 知乎搜索）：
  1. L1：任务表渲染、状态 Pill、hover/点击行预览定位、预览卡趋势/品牌、导出 CSV、定时监测进编辑弹窗。
  2. 点任务名进 L2：关键词列表、点关键词看右卡 KPI + 结果表、「· 正文」标记、no_cookie 状态条、
     启动监测跑整任务、返回回 L1。
  3. 空态：无任务 / 无结果 / 加载失败重试。
