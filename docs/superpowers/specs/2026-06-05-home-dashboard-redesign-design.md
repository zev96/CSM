# 首页工作台按「图一」重做 — 设计

- 日期：2026-06-05
- 分支：`feat/home-dashboard-redesign`
- 状态：设计已与用户确认，待 spec 复核 → writing-plans

## 1. 目标

把 `HomeView` 工作台从现有「6 张列表+折线监测卡 + 最近文档」改成用户提供的「图一」bento 布局：3 张大数字卡 + 高权重信源榜 + GEO 半圆仪表盘 + 评论留存卡 + 最近文档，并把每张卡接上**最近 7 天**的真实指标。

## 2. 范围

**做：**
- 重排 `HomeView` 为 bento 网格（沿用图一）。
- 新建 3 类卡片组件（大数字 `StatCard`、半圆 `GaugeCard`、信源榜 `SourceLeaderboardCard`）。
- 重做 `CommentRetentionCard`（改用专用 7 天端点）。
- `RecentDocsCard` 仅微调样式贴合图一。
- 新增 2 个后端聚合端点（GEO 汇总曝光、全局信源榜）+ 3 个排名/异动端点补 `changed_prev`。
- 移除首页「视频抓取」卡（`VideoMiningCard` 不再挂在 HomeView；组件文件保留备用）。

**不做：**
- LeftNav / 其它页面 / 路由不动。
- 不动 `CreateArticleHero`（问候 + 创建栏，图一顶部原样保留）。
- 不重构监测中心既有页面。

## 3. 布局（bento 网格）

顶部 `CreateArticleHero` 不变；下方 4 列网格（精确 span 在运行中的桌面端用 vite HMR 微调到与图一一致）：

```
┌──────────┬──────────┬──────────┬───────────────┐
│ 百度SEO   │ 知乎问题  │ 知乎搜索  │ 高权重信源     │  ← 右列跨 2 行
├──────────┴──────────┼──────────┤ (域名榜 top-N)│
│ 评论留存率           │ GEO 仪表  │               │
│ (大% + 折线 + 平台tab)│ (半圆)    ├───────────────┤
│                      │          │ 最近文档       │
└──────────────────────┴──────────┴───────────────┘
```

## 4. 卡片数据映射

| 卡片 | 组件 | 主数字 | 徽章 | 数据源 |
|---|---|---|---|---|
| 百度SEO / 知乎问题 / 知乎搜索 | `StatCard` ×3 | `kpis.changed_keywords`（排名升+降的关键词数） | 该数较上一个 7 天净增减 | 现有 `/api/monitor/history/{baidu-keyword,zhihu-ranking,zhihu-search}?range=7d` + 补 `changed_prev` |
| 高权重信源 | `SourceLeaderboardCard` | top-N 域名 + 当前排名 | 排名较上一个 7 天的变化 | **新端点** `/api/monitor/geo/citations/leaderboard?days=7&limit=N` |
| GEO | `GaugeCard`（半圆 0–100） | 全局总曝光率 ×100 | ↑/↓% 较上一个 7 天 | **新端点** `/api/monitor/geo/summary?range=7d` |
| 评论留存率 | `CommentRetentionCard`（重做） | 各平台聚合 rate ×100 | ↑/↓ vs `rate_prev` | 现有 `/api/monitor/history/comment-retention?range=7d` |
| 最近文档 | `RecentDocsCard`（样式微调） | 近 7 天文档卡 | — | 现有 `listRecent(n, 7)` |

「视频抓取」卡：从 HomeView 移除。

## 5. 后端新增

1. `GET /api/monitor/geo/summary?range=7d`
   → `{ range, soc, soc_prev, delta, band, mentioned, ok_cells, task_count }`
   - `soc` = Σmentioned / Σok_cells（**全局口径**，跨所有 geo_query 任务，近 7 天）。
   - `soc_prev` = 上一个 7 天同口径；`delta = soc - soc_prev`。
   - `band` ∈ {low, mid, high}（阈值见 §7.4）。
   - 实现：`history_service.get_geo_summary(range)`，复用既有日期分窗逻辑 + `geo/metrics.py` 的 soc 定义。

2. `GET /api/monitor/geo/citations/leaderboard?days=7&limit=8`
   → `{ days, leaderboard: [{ domain, source_type, count, weight, rank, rank_prev, rank_delta }] }`
   - 复用 `csm_core/monitor/geo/storage.py:citation_leaderboard`，**去掉单任务限定**做全局聚合；再算上一个 `days` 窗口的排名得 `rank_prev` / `rank_delta`。

3. 3 个 ranking/异动 端点补 `kpis.changed_prev`（上一个 7 天窗口的 `changed_keywords` 同值），供大数字卡算「较上周净增减」。
   - 备选（若想零后端改动）：徽章退化为 `changed_up − changed_down`（净方向，现成字段），但语义不是「较上周」。**默认走 `changed_prev`。**

## 6. 前端组件

- `components/home/StatCard.vue`（新）：标题 + 大数字 + 涨跌 pill + 点击跳监测中心对应 tab。3 张卡各自薄包一层取数 + 跳转。
- `components/home/GaugeCard.vue`（新）：SVG 半圆仪表（0–100，刻度 + 指针/填充弧），中心大数字 + 档位文字 + 周对比 pill。
- `components/home/SourceLeaderboardCard.vue`（新）：序号 + 域名 + 站点名 + 排名变化 pill 的列表。
- `components/home/CommentRetentionCard.vue`（重做）：大% + `Sparkline`/折线 + 平台 tab（B站/快手/抖音）切换显示，改用 `/history/comment-retention`。
- `HomeView.vue`：替换 Row2/Row3 为 bento 网格，移除 `VideoMiningCard` 引入。
- 复用 `Sparkline`、`Icon`、`card-frosted` 等既有 UI 原子；空状态/加载态沿用现有卡片的处理风格。

## 7. 已确认的口径（用户拍板）

1. GEO 总曝光率 = Σmentioned / Σok_cells（全局），非各任务 soc 简单平均。
2. 高权重信源 = 全部 GEO 任务合并 top-N，徽章 = 排名周对比。
3. 评论留存大% = 各平台今日 rate 聚合，徽章 = 较上周（`rate_prev`）。
4. GEO 档位标签：优先复用 `geo/` 既有阈值；若无则 `<40` 低 / `40–70` 中等 / `>70` 高曝光。
5. 大数字卡数字 = 现成 `changed_keywords`（升+降），徽章 = 较上一个 7 天净增减。

## 8. 测试

- 后端：2 个新端点 + `changed_prev` 字段加 pytest（空数据 / 单任务 / 多任务聚合 / 上一窗口对比）。
- 前端：每个新卡片组件 vitest 挂载测试（有数据 / 空态 / 加载态渲染）。
- 真机：运行中的桌面端走 vite HMR 实时核对版式与图一一致（用户在屏幕上确认）。

## 9. 风险与备注

- **planned UI overhaul**：记忆里有「B+C 组件库替换 + IA 重做即将启动」。本次是首页版式重做 —— 数据接线（后端聚合端点）可长期复用，卡片视觉若被 B+C 冲掉影响有限。已按用户明确要求推进。
- 多数据为真实共用库（`%LOCALAPPDATA%/CSM-Data`），开发期读真任务/历史；空数据时各卡须有干净空态。
- `tauri.conf.json` 的 `resources:[]` 是 dev-only 改动，**不进本功能 PR**。
