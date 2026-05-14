# 历史报告页重构：评论留存率 + 知乎排名分析

## 背景

`MonitorView.vue` 的「历史报告」tab 当前是一张单一表格：每行一个日/周
bucket，列固定为「报告名 / 覆盖 / 时间 / 异动数 / 操作」。这套布局把
评论留存和知乎排名两套不相干的业务指标揉在一起，用户看不到：

- 评论端：哪个平台在掉评论、什么时候开始掉、被删的具体是哪些视频
- 知乎端：品牌在监测问题里的占位变化、谁的占有率掉了 / 谁起来了

需求是把「历史报告」拆成**两个 sub-page**，分别给评论端和知乎端各自
一套分析视图。两页结构同源（时间范围切换 / KPI 卡 / 主图 / 可跳转的
drill-down 表），指标根据业务差异化。

mockup 验证过两轮，最终骨架：
- 评论页：[.superpowers/brainstorm/2685-1778748075/content/comment-retention-layout-v3.html](.superpowers/brainstorm/2685-1778748075/content/comment-retention-layout-v3.html)
- 知乎页：[.superpowers/brainstorm/2685-1778748075/content/zhihu-ranking-layout.html](.superpowers/brainstorm/2685-1778748075/content/zhihu-ranking-layout.html)

## 范围

**做：**

- `MonitorView.vue` 的「历史报告」tab 内新增子级 pivot：「评论留存率」/「知乎排名」
- 两个子页 UI（KPI / Chart.js 折线 / drill-down 表）
- 每页一个时间范围切换（1d / 7d / 30d），1d 自动隐藏折线 + sparkline
- 后端补两个聚合端点（评论端 + 知乎端，按日 bucket）
- 引入 `chart.js` + `vue-chartjs` 依赖（评估后采用，仓库原本无图表库）
- drill-down 行可点击跳转到「平台评论」/「知乎问题」对应任务的 L2/L3 详情

**不做（YAGNI）：**

- 不动现有任务列表 / 编辑 / 删除流程
- 不引入 ECharts / Recharts 等竞品图表库
- 不新增「按月 / 按季度」时间范围
- 不做 CSV / Excel 导出（用户没提）
- 不做品牌词多目标对比（当前知乎任务只有 1 个品牌词字段 `target_brand`）
- 不调整后端任务 schema，全部聚合在视图层算

## 架构

```
historyTab (新 sub-pivot)
├── 评论留存率 sub-page          ── 默认
│   ├── <RetentionRangePicker>   1d / 7d / 30d
│   ├── <RetentionKpiCards>      3 platforms × KPI（in-card sparkline + delta + 在显/被删）
│   ├── <RetentionTrendChart>    Chart.js Line，3 线，仅 7d/30d 显示
│   └── <RetentionDeletedTable>  drill-down，row → 跳 comment tab L3
└── 知乎排名 sub-page
    ├── <ZhihuRangePicker>       1d / 7d / 30d
    ├── <ZhihuKpiCards>          监测问题数 / 平均占有率 / 异动问题数
    ├── <ZhihuTrendChart>        Chart.js Line，双轴（占有率 % + 异动数）
    └── <ZhihuQuestionTable>     drill-down，row → 跳 zhihu tab L2

后端：
GET /api/monitor/history/comment-retention?range=1d|7d|30d
GET /api/monitor/history/zhihu-ranking?range=1d|7d|30d
```

**关键约束 — 文件大小：** `MonitorView.vue` 已经接近 3300 行。本次新增
两个子页千万不能塞回这个文件里，必须拆成独立组件文件。`MonitorView`
保留 sub-pivot 状态 + 两个子组件的 mount 点即可，子组件各自管自己的
数据 / 渲染 / 跳转。

## 文件结构

**新增**：

- `frontend/src/components/monitor/history/RetentionPage.vue`
  - 评论留存率主页面（包含 range picker / KPI / chart / table）
  - emit `'navigate'` 事件，payload `{platform: 'bilibili'|'douyin'|'kuaishou', batchName: string, taskId: number}`
- `frontend/src/components/monitor/history/ZhihuRankingPage.vue`
  - 知乎排名主页面（同上结构）
  - emit `'navigate'` 事件，payload `{taskId: number}`
- `frontend/src/components/monitor/history/LineChart.vue`
  - 通用折线图组件，封装 `vue-chartjs` `Line`，提供我们的色板默认值
  - props: `series: {label, color, data}[], labels: string[], yAxisFormatter, dualAxis?`
  - 两个 sub-page 共用，避免 chart.js 配置散落

**修改**：

- `frontend/src/views/MonitorView.vue`
  - 加 `const historySubtab = ref<"retention" | "zhihu">("retention")`
  - 历史报告 tab 内容替换为「sub-pivot + 子组件 mount」
  - 暴露跳转回调函数：
    - `goToCommentTask(platform, batchName, taskId)`: 设 `activeTab = "comment"` / `commentSubtab` / `selectedCommentTaskId` / `selectedVideoId`
    - `goToZhihuTask(taskId)`: 设 `activeTab = "zhihu"` / `selectedTaskId`
  - 删掉旧的「报告 / 覆盖 / 时间 / 异动 / 操作」表格代码（含相关 demo `SAMPLE_REPORTS`）和不再使用的 `loadReports` + `reports.value`
- `frontend/package.json`
  - 新增 `chart.js` (^4.x) + `vue-chartjs` (^5.x) 依赖

**新增（后端）**：

- `sidecar/csm_sidecar/services/monitor_service.py`
  - `get_comment_retention_history(range_days: int) -> dict`
  - `get_zhihu_ranking_history(range_days: int) -> dict`
- `sidecar/csm_sidecar/routes/monitor.py`
  - `GET /api/monitor/history/comment-retention?range=1d|7d|30d`
  - `GET /api/monitor/history/zhihu-ranking?range=1d|7d|30d`

**删除（验证完无外部调用方）**：

经 grep 全仓确认 `get_reports` / `/api/monitor/reports` / `openReport` /
`selectedReport` / `kind="history_report"` 这些代码路径只服务于旧的历史
报告页，本次一并清理：

- `MonitorView.vue`：`reports` ref / `SAMPLE_REPORTS` / `loadReports()` /
  `openReport()` / `selectedReport` ref / `clearEditOnClose` 里对它的清空 /
  旧报告表格的整段 template
- `monitor_service.py`：`get_reports()` + `_bucket_key()` 辅助
- `routes/monitor.py`：`GET /api/monitor/reports` 路由
- `sidecar/tests/test_monitor_routes.py`：`get_reports` 相关测试（替换为
  新两端点的测试，见「测试策略」）
- `AlertDetailModal.vue`：`kind === "history_report"` 分支及其专用
  template / props / 派生 computed（modal 只保留 `zhihu_alert` /
  `comment_alert` 两种 kind，跟告警 hero stack 对齐）
- `docs/migration/feature-ui-mapping.md`：把「历史监测报告」一行的引用
  更新到新两个 sub-page

## 设计

### sub-pivot 切换

历史报告 tab 内右上角加一行 pill 切换，跟现有平台评论 tab 内的平台
切换同款：

```vue
<div class="csm-pill-row">
  <button :class="{active: historySubtab==='retention'}" @click="historySubtab='retention'">
    评论留存率
  </button>
  <button :class="{active: historySubtab==='zhihu'}" @click="historySubtab='zhihu'">
    知乎排名
  </button>
</div>
```

切换不闪动用同样的 atomic-swap 模式：先把新页的 data 拉到临时变量再
赋值。但本次每页只有 1-2 个 GET，简单 `loading` flag 就够，不必复用
`loadTasksAndSnapshotsAtomic`。

### 评论留存率页

**KPI 卡（3 张）**

每平台一张，结构相同：

| 字段 | 来源 | 示例 |
|---|---|---|
| 标题 + 色点 | `PLATFORM_MAP[].label/color` | B 站 |
| 主数字 | 当日 retained / total | 62% |
| Delta chip | 当日值 vs N 日前同范围值 | ↓ 8 pts |
| Sparkline | 该平台近 7 天每日留存率 | inline 30px 高 |
| 二级指标 | retained 数 / total 数 / 被删数 | 在显 14/22 · 被删 8 |

**主图（仅 7d / 30d 显示）**

`<LineChart>` 三条线 = 三平台。X 轴日期标签，Y 轴 0-100%。
- B 站 = `--primary` `#ee6a2a`
- 抖音 = `#1e1c19`
- 快手 = `--yellow` `#f5c042`

`vue-chartjs` 默认 hover tooltip 已经够用；我们配置 `tooltip.intersect: false / mode: 'index'`
让 hover 在 X 轴某点时同时显示三平台值。

**drill-down 表 — 被删 / 折叠评论**

筛选 pill：全部 / B 站 / 抖音 / 快手
列：平台 chip / 评论 + 视频元信息 / 排位变化 chip / 时间 / chevron
排序：默认按时间倒序
跳转：整行 `cursor: pointer`，hover `background: var(--card-2)`，
hover 时行尾 chevron `›` 变 `--primary-deep` + 右移 2px
点击：`emit('navigate', {platform, batchName, taskId})`

数据来源：从 `comment-retention` 响应的 `events: [{platform, batch_name,
task_id, comment_text, video_title, rank_from, rank_to, status, at}, ...]`
直接渲染，后端已经按时间倒序、按 range 过滤好了。

### 知乎排名页

**KPI 卡（3 张）**

| 标题 | 主数字 | Delta | 二级 |
|---|---|---|---|
| 监测问题数 | 当前 enabled 任务数 | 上周新增数 | 覆盖品牌词数 |
| 品牌占有率（平均） | ∑matched_count ÷ ∑top_n | vs N 日前 | 命中位总数 / 总 top-N |
| 排名异动问题数 | range 内最佳 rank 或 matched_count 变了的问题数 | "↓多 / ↑多" 简评 | mini stacked bar：每日 ↑↓ 分布 |

**主图（双轴）**

`<LineChart :dualAxis="true">`：
- 左轴：占有率 % 0-100，橙色线
- 右轴：异动问题数 0~10，黑色线
- 两条线共享 X 轴日期

**drill-down 表 — 问题列表**

筛选 pill：全部 / ↓下降 / ↑上升 / 新上榜 / 掉出 Top
- ↓下降 = `rank > rank_prev` OR `matched_count < matched_count_prev`
- ↑上升 = 反向
- 新上榜 = prev 无命中、当前有命中
- 掉出 Top = prev 在 top_n 内、当前不在

列：方向标 `▲▼—` / 问题 + 命中位 + 品牌 chip / 占有率（数字 + 进度条）/
最佳排名变化 chip / 时间 / chevron

跳转：`emit('navigate', {taskId})` → 切到知乎问题 tab + `selectedTaskId`

### 跳转回调实现

`MonitorView.vue` 已有 `selectedTaskId` / `activeTab` / `commentSubtab`
/ `selectedCommentTaskId` / `selectedVideoId` 这些 ref。两个跳转回调：

```ts
async function goToCommentTask(platform: CommentPlatform, batchName: string, taskId: number) {
  activeTab.value = "comment";
  commentSubtab.value = platform;
  // 等 watch(activeTab) / watch(commentSubtab) 的 atomic load 跑完
  await nextTick();
  selectedCommentTaskId.value = batchName;
  selectedVideoId.value = `task-${taskId}`;
}

function goToZhihuTask(taskId: number) {
  activeTab.value = "zhihu";
  // watch(activeTab) atomic load 后 selectedTaskId 会回到 tasks[0]，
  // 等 load 完再设
  nextTick(() => {
    selectedTaskId.value = taskId;
  });
}
```

`nextTick` 等的是已有的 `watch(activeTab)` / `watch(commentSubtab)`
里 `await loadTasksAndSnapshotsAtomic(...)` 跑完，之后再赋值，否则
atomic load 内部的「`selectedTaskId.value = newTasks[0].id`」会盖掉
我们的设置。如果 nextTick 不够，要用 `flushPromises` 或者把跳转 await
完整 chain。落地时验证。

### 时间范围 1d 特殊处理

`range=1d` 时：
- 后端聚合粒度也是按日 bucket，但 range_days=1 只有 1 个 bucket
- 前端组件根据 `range === '1d'`：
  - 隐藏主图 (`<RetentionTrendChart>` / `<ZhihuTrendChart>`)
  - 隐藏 KPI 卡里的 sparkline（24h 内没线可画）
  - KPI 卡显示「今日」语义而非「7 天均值」
- Delta chip 在 1d 下基于「今天 vs 昨天」算（不是 vs 7 天前）

### 后端聚合接口

#### `GET /api/monitor/history/comment-retention?range=1d|7d|30d`

```jsonc
{
  "range": "7d",
  "platforms": {
    "bilibili_comment": {
      "label": "B 站",
      "color_hint": "primary",      // 前端按 PLATFORM_MAP 自己映射，这个字段可省
      "current_retained": 14,
      "current_total": 22,
      "current_deleted": 8,
      "rate_today": 0.636,
      "rate_prev": 0.711,           // N 日前同范围的对照值
      "daily_series": [             // 长度 = range_days
        {"date": "2026-05-08", "retained": 18, "total": 22, "rate": 0.818},
        ...
      ]
    },
    "douyin_comment": { ... },
    "kuaishou_comment": { ... }
  },
  "events": [                       // 最近 N 条被删 / 折叠
    {
      "platform": "kuaishou_comment",
      "task_id": 28,
      "batch_name": "0514",
      "video_title": "X-7Ellfyy6sQUWfo",
      "comment_text": "抽烟可以，但麻烦避开人群不行...",
      "rank_from": 3,
      "rank_to": null,              // null = 掉出 top_n / 被删
      "status": "deleted",          // deleted | folded
      "at": "2026-05-14T14:32:00Z"
    },
    ...
  ]
}
```

`daily_series` 后端算法：
1. `SELECT r.checked_at, r.metric_json, t.type FROM monitor_results r JOIN monitor_tasks t WHERE t.type IN ('bilibili_comment','douyin_comment','kuaishou_comment') AND r.checked_at >= now() - range_days days`
2. 按 `(platform, date(checked_at))` 分组
3. 每组：retained = `sum(metric.matched == True)`、total = `sum(status == 'ok' AND metric != null)`、rate = retained / total
4. 同一 task 同一天有多次 result 时，取最新一次（用 `MAX(checked_at)` per task）

`events` 算法：在 range 内找出 `metric.matched` 由 True → False 的转换，
或当前 status = ok 且 matched = False（持续被删态首次出现）。按时间倒
序限 50 条。`rank_from` 从上一次成功结果的 `matched_rank` 取（评论端
其实没有「rank_from」概念，但有「上次命中位置」从 metric.matched 时
对应的 hot_comments 里取）。**简化版**：先只标 status: deleted/folded
不算 rank_from/rank_to，UI 显示「在显 → 无」即可。第一版 v0 走这套。

#### `GET /api/monitor/history/zhihu-ranking?range=1d|7d|30d`

```jsonc
{
  "range": "7d",
  "kpis": {
    "monitored_questions": 25,
    "questions_added_this_week": 2,
    "brands_covered": 1,
    "avg_share_today": 0.28,
    "avg_share_prev": 0.31,
    "hit_count_total": 70,
    "topn_total": 250,
    "changed_questions": 7,
    "changed_up": 3,
    "changed_down": 4
  },
  "daily_series": [
    {"date": "2026-05-08", "avg_share": 0.30, "changed_count": 2, "changed_up": 1, "changed_down": 1},
    ...
  ],
  "questions": [                    // 全部 enabled 任务，前端 filter
    {
      "task_id": 12,
      "title": "哪个空气净化器好用？室内除甲醛去二手烟",
      "target_brand": "拾梧",
      "matched_count": 3,
      "matched_count_prev": 5,
      "top_n": 10,
      "matched_ranks": [2, 6, 11],
      "best_rank": 2,
      "best_rank_prev": 2,
      "change_kind": "down",        // down | up | new | dropped | flat
      "checked_at": "2026-05-14T14:20:00Z"
    },
    ...
  ]
}
```

`change_kind` 算法：
- 拿当前 result（status=ok 最新一条）vs prev result（同 task 倒数第二条）
- prev 不存在 → `change_kind = "flat"`（首次监测视为持平，避免误标）
- prev 有命中 + 当前无命中 → `dropped`（掉出 top）
- prev 无命中 + 当前有命中 → `new`（新上榜）
- 否则比较 `(matched_count, -best_rank)` 字典序：增 → `up`，减 → `down`，等 → `flat`

### Chart.js / vue-chartjs 引入

`frontend/package.json` 加：
- `"chart.js": "^4.4.0"`
- `"vue-chartjs": "^5.3.0"`

`LineChart.vue` 内只 import 需要的 controllers/elements/scales 避免
bundle 膨胀（chart.js v4 是 tree-shakable）：

```ts
import { Line } from "vue-chartjs";
import {
  Chart, LineController, LineElement, PointElement,
  CategoryScale, LinearScale, Tooltip, Legend, Filler,
} from "chart.js";
Chart.register(
  LineController, LineElement, PointElement,
  CategoryScale, LinearScale, Tooltip, Legend, Filler,
);
```

### Sparkline 沿用现有

KPI 卡里的 mini sparkline 不上 Chart.js（28px 高度，配置开销 > 自画
SVG）。沿用 [Sparkline.vue](frontend/src/components/ui/Sparkline.vue)
现有组件即可。

## 数据流

```
sub-pivot 切换 / range 切换
   │
   ▼
fetch /api/monitor/history/<sub>?range=<r>
   │
   ▼
组件 ref 接住 response → KPI / Chart / Table 三块同时渲染
   │
   ▼
用户点 drill-down 行
   │
   ▼
emit('navigate', payload) → MonitorView.vue 调 goToXxxTask
   │
   ▼
activeTab/commentSubtab/... 切换 → 现有 watch atomic-load 跑 → L2/L3 自动定位
```

## 错误处理

- 后端 503（storage 没 init）→ 显示「监测系统未就绪」（沿用现有 `failed` 状态文案）
- 网络失败 → toast.error + 组件内 retry 按钮
- 任意一项 KPI / chart / events 缺失 → 该块独立显示「暂无数据」占位，
  不挂整页（一个评论端没数据不该把知乎端也挡了）
- 跳转目标 `taskId` 在目标 tab 已不存在（任务被删）→ toast.warn
  「目标任务已删除」，落到批次列表 L1（不下钻 L3）

## 测试策略

**后端**（pytest）：
- `tests/sidecar/test_history_routes.py`（新增）
  - 空 DB → 两端点返 `{daily_series: [], events: [], questions: []}` 不挂
  - mock 几条 result 行，验证日 bucket 聚合正确
  - 验证 `change_kind` 分类（新上榜 / 掉出 top / 升降 / 持平）
  - 验证 range 边界（1d / 7d / 30d 各自截断）

**前端**：跟现有惯例一致，前端没装 vitest，靠 dev 模式手动跑 mockup
对照 + Tauri dev 验证跳转链路。

## 验证清单（手动）

切到「历史报告 → 评论留存率」：
- [ ] 顶部 sub-pivot 高亮「评论留存率」
- [ ] range picker 默认 7d，切 1d 隐藏折线 + sparkline，切 30d 折线点更密
- [ ] 3 KPI 卡显示各平台 retained/total + delta + sparkline
- [ ] 主图三条线，hover 显示三平台同日值
- [ ] drill-down 表行可点 → 跳到「平台评论 → 对应平台 → 对应批次 → L3 视频详情」

切到「历史报告 → 知乎排名」：
- [ ] 3 KPI 卡显示问题数 / 平均占有率 / 异动问题数
- [ ] 主图双轴线（占有率% 左轴橙色 / 异动数 右轴黑色）
- [ ] 筛选 pill 切换正确过滤
- [ ] drill-down 表行可点 → 跳到「知乎问题 → 该任务 L2」

跨页：
- [ ] 历史报告 ↔ 平台评论 ↔ 知乎问题 三 tab 切换不闪动（沿用 atomic load）
- [ ] 跳转后再返回历史报告，sub-pivot 状态保留

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Chart.js bundle 体积 +70KB | tree-shake 只 register 用到的 controllers；Tauri 桌面端不在意 50KB 量级 |
| 后端聚合慢（30 天大量 result 行）| `monitor_results.checked_at` 已建索引；range_days = 30 单查询 < 100ms 实测够 |
| 跳转 nextTick 时机不准 | 落地时手动验证；如果出错改成 `await` 链式等 atomic load 完整完成 |
| MonitorView.vue 已经超大 | 强制把子页拆成独立组件文件，MonitorView 只做 sub-pivot + mount |
| Chart.js 与现有 Sparkline.vue 风格冲突 | LineChart.vue 内默认色板对齐 `--primary` / `--ink` / `--yellow`，跟 sparkline 同色 |

## 不动的（YAGNI 再列一次）

- 不做按月 / 季度时间范围
- 不做导出（CSV / Excel）
- 不做品牌词多目标对比、品牌词切换器
- 不做按问题分类 / 标签的高级过滤
- 不做评论文本相似度热力图等高级视图
- 不引入第二个图表库 / 不替换 vue-chartjs
