# CSM 批量改进设计：评论提速 · 引流预筛 · RPA 隐窗 · 数据中心/首页/GEO UI

- 日期：2026-06-04
- 分支：`claude/elastic-moore-fa05f4`
- 状态：设计已与用户确认，待评审 → 出实现 plan

## 1. 背景与范围

用户提出 6 项需求。摸底后拆成 **4 条相互独立的工作流（A/B/C/D）**，本文统一设计；实现时可拆成 4 个独立 plan / PR，互不阻塞。

| 原始需求 | 工作流 |
|---|---|
| ① 监控「平台评论」抓取提速 + 进度条不显示 | **A** |
| ⑥ 引流「评论视频」抓取前预筛、≤3 条种草跳过 | **B** |
| ④ GEO 抓取浏览器隐藏；⑤ 百度抓取浏览器不抢视觉 | **C** |
| ② 数据中心新增知乎搜索/GEO 页、知乎排名改名知乎问题；③ 首页新增知乎搜索/GEO 卡片 | **D** |

### 已确认决策摘要

| 决策点 | 结论 |
|---|---|
| 评论提速取舍 | **可调档 + 保守默认**（抓取条数/节流提为可配置，默认维持现值防软封） |
| 引流品牌词来源 | **引流任务新增 `brand_keywords` 字段**（品牌词+别名），不做全局品牌设置 |
| 预筛阈值/动作 | **含品牌词评论 ≥3 → 标 `excluded` + 记原因/命中数**（仍入库、可恢复）；<3 正常入库 |
| RPA 隐藏方案 | **移到屏幕外**（有头渲染防风控 + 验证码可人工），不使用 headless、不做 always-on-bottom |
| GEO 矩阵单元格 | **方案 A：名次 + 颜色**（点格下钻回答原文+引用信源） |
| 高权重信源权重 | `weight = 被引频次 × 覆盖平台数 × 信源类型权威度` |
| 信源聚合粒度 | 按**规范信源**聚合：默认主域名合并（`*.zhihu.com`→知乎）；**百度系按产品拆**（百家号/百科/知道/贴吧）、`mp.weixin.qq.com`→微信公众号 |
| 数据中心结构 | 知乎排名→**知乎问题**（改名）+ 新增**知乎搜索**+**GEO**，共 5 子页 |
| 首页卡片 | 4→6，**3×2 网格**，新增知乎搜索卡 + GEO 卡 |

### 现状关键定位（摸底结论）

- 评论监控适配器：`csm_core/monitor/platforms/{bilibili,douyin,kuaishou}_comment.py`（`fetch(task, cancel_token, **kwargs)->MonitorResult`），翻页内核 + `_comment_common.py`。
- 进度管线（已存在、评论侧未接）：`monitor_loop._progress_cb` → `MonitorEvent(kind="progress", progress_current/total)` → `monitor_bus` → SSE `/api/monitor/events` → 前端 `stores/monitorStatus.ts.taskProgress` → `ProgressBar.vue`。**仅百度适配器调用了 progress_cb**。
- 节流：`csm_core/browser_infra/rate_limit.py` `RequestPacer`（默认 5–15s）；`scrape_top_n` 默认 150（`_comment_common.py`）。
- 引流（mining）：`mining_service` → `csm_core/mining/runner.py` 串行遍历平台 → 各 `platforms/{douyin,bilibili,kuaishou}_search.py`。`VideoCard`（`mining/models.py`）**只采视频元数据、不采评论**。`videos` 表已有 `excluded` / `already_commented` / `commented_at`。`MiningJob` 无品牌词字段。进度走独立通道 `job.progress{platform:{got,target,phase}}`。
- RPA 启动：`csm_core/browser_infra/mining_browser.py launched_page()`、`monitor/geo/providers/rpa/_session.py`、`monitor/drivers/baidu_browser.py`、`browser_infra/patchright_pool.py`。**均无窗口定位**；GEO RPA 恒有头、百度 patchright 模式默认 headless=True、原生 Chrome 模式强制有头。
- GEO：`csm_core/monitor/geo/`（models/providers/classify/metrics/storage）。`Citation/ClassifiedCitation` 只有 `url/title/domain/source_type`，**无权重字段**；`classify.py` 已用 tldextract + 「域名→类型」规则表。前端实时模块 `components/monitor/geo/GeoTaskModule.vue`（已有概览/平台对比/竞争·信源 + 一批图表组件）。
- 数据中心：`views/DataCenterView.vue`（3 子页：知乎排名 `ZhihuRankingPage.vue` / 平台评论 `RetentionPage.vue` / 百度排名 `BaiduSEOAnalytics.vue`）；历史聚合端点形如 `GET /api/monitor/history/zhihu-ranking?range=`。
- 首页：`views/HomeView.vue`，4 卡（`BaiduSeoCard/ZhihuCard/CommentRetentionCard/VideoMiningCard`），数据来自 `/api/monitor/summary`。

---

## 2. Stream A — 监控「平台评论」进度条 + 提速

### 问题
1. **进度条不显示**：评论适配器翻页时从不调用 `progress_cb`，后端不发 `progress` 事件，前端进度条永远不出现（管线本身是通的，百度侧能显示）。
2. **慢**：`scrape_top_n=150`（~8 页）× 每页 `RequestPacer` 5–15s 串行 = 单任务 40–120s；多任务受每平台并发 2 限制。

### 设计
**进度（接通现有管线）**
- 三个评论适配器的翻页循环改为接收并调用 `progress_cb`：每抓完一页回调一次 `progress_cb(current=已扫描评论数, total=scrape_top_n)`。
- `monitor_loop._run_one()` 已为适配器准备了 `progress_cb`（百度在用），将其透传给评论适配器即可（统一 adapter `fetch(..., progress_cb=...)` 签名）。
- **进度语义**：`current = 已扫描评论数`，`total = scrape_top_n`（命中目标评论提前结束时直接置满）。
- 前端：确认「平台评论」监控模块组件是否已渲染 `ProgressBar`（读 `monitorStatus.taskProgress[taskId]`）；若无则补一个，与 `ZhihuSearchModule` 的进度条一致。

**提速（可调档 + 保守默认）**
- 将 `scrape_top_n` 与节流 `delay_min/delay_max` 提为**可配置**：`MonitorConfig` 增加默认值 + 任务 `config` 可覆盖（`config.scrape_top_n`、`config.pacing_min/pacing_max`）。
- **默认值维持现状**（150 / 5–15s）以防软封（用户 5 月曾遇 cookie 软封）；用户可在设置/任务里手动调小以加速。
- 不改并发默认（每平台 2），但同样提为可配置以备调。

### 错误处理
- `progress_cb` 抛错不得中断抓取（包一层 try/ignore）。
- 配置项做边界保护：`scrape_top_n` 下限（如 ≥20）、`pacing_min ≤ pacing_max` 且 `pacing_min` 有下限（如 ≥1s）防止被调成 0 触发风控。

### 测试
- 单测：评论适配器在 mock 翻页下按页回调 `progress_cb`，序列单调递增、最终置满。
- 单测：配置覆盖生效（任务 config 覆盖 MonitorConfig 默认）。
- 手测：起一个 `*_comment` 任务，观察前端进度条出现并推进。

---

## 3. Stream B — 引流「评论视频」预筛跳过

### 设计
**数据模型**
- `MiningJob` / `StartJobRequest`（`csm_core/mining/models.py`）新增 `brand_keywords: list[str] = []`（品牌词 + 别名）。
- `videos` 表（`csm_core/mining/storage.py`）新增：`brand_comment_hits INTEGER`（命中评论数，null=未筛/筛失败）、`exclude_reason TEXT`（值如 `seeded_full`）；复用既有 `excluded`。

**抽取可复用的「抓单视频评论」内核**
- 从 `{bilibili,douyin,kuaishou}_comment.py` 抽取纯抓评论函数：`fetch_video_comments(platform, video_url_or_id, limit, ctx) -> list[str]`（返回评论文本），供监控与引流共用。监控适配器改为调用它。
- 引流侧复用 mining 的 patchright context / page（`page.evaluate` fetch 技术），避免另开会话。

**预筛流程（mining runner）**
- 某平台 `search` 收齐候选后，对 `comment_count > 0`（或元数据缺失时一律检查）的视频跑 **prefilter pass**：抓**第一页**评论（`limit≈30–50`，1 次请求），统计含**任一** `brand_keywords` 的评论数 `hit`。
- 判定：`hit ≥ 3` → 入库但 `excluded=1, exclude_reason="seeded_full", brand_comment_hits=hit`；`hit < 3` → 正常入库（记 `brand_comment_hits=hit`）。
- `brand_keywords` 为空 → 跳过整个预筛（保持旧行为）。

**进度**
- prefilter 作为独立阶段上报：`job.progress[platform].phase="prefilter"`（与 `scrolling/done` 并列），`got/target` 反映已筛视频数。

**性能 / fail-open**
- 只抓第一页、只对有评论的视频；沿用平台节流与熔断。
- 抓评论失败（风控/超时）→ **不排除**（fail-open，`brand_comment_hits=null`），避免误杀候选；记日志（raw response logging 风格）。

### 测试
- 单测：给定一组带评论的视频，`hit≥3` 标排除、`<3` 保留、空 `brand_keywords` 全保留、抓取失败 fail-open。
- 单测：`brand_keywords` 多别名任一命中即计数。
- 手测：真实关键词跑一次引流，验证已铺满视频被标排除且 UI 可见可恢复。

---

## 4. Stream C — RPA 浏览器移到屏幕外

### 设计
**统一隐窗能力（off-screen）**
- 在浏览器启动 infra（`mining_browser.launched_page` / `geo/providers/rpa/_session` / `drivers/baidu_browser` / `patchright_pool`）统一支持 `hidden_window: bool=True`：
  - 启动参数追加 `--window-position=<offscreen>`（如 `-32000,-32000`）并保留既有 `--window-size`（窗口照常渲染，无 headless 指纹）。
- 抽一个共享 helper（如 `browser_infra/window_util.py`）：`hide_window(page)` / `surface_window(page)`，基于 **CDP `Browser.getWindowForTarget` + `Browser.setWindowBounds`** 在运行时移动窗口（off-screen ↔ 可见坐标 + 置前）。

**人工介入时上浮**
- 检测到验证码 / 登录态失效（复用各 RPA 既有检测，如 douyin captcha 轮询、geo `open_login`）→ `surface_window(page)` 移回可见区并置前，提示用户处理；完成后 `hide_window(page)` 移回屏外。

**范围**
- GEO RPA（DeepSeek/Kimi/元宝）与百度同款隐窗；**不使用 headless**（避免风控 + 验证码不可人工）。
- 百度 patchright 模式本就支持 headless，但本流统一改为「有头 + 屏外」以保留验证码人工能力且行为一致。

### 错误处理
- CDP 移动失败 / 坐标越界 / 多显示器异常 → 回退为正常窗口（不致命，记日志）。
- off-screen 坐标取足够负值，避免落在副屏可见区。

### 测试
- 手测（关键）：GEO 与百度任务运行时窗口不出现在可见区、不抢焦点；触发验证码时窗口自动上浮可操作；fresh 机验证（dev 机有缓存）。

---

## 5. Stream D — 数据中心 & 首页 & GEO UI

### D1. 数据中心结构
- `DataCenterView.vue` 子页：`知乎排名`→改显示名 `知乎问题`（底层任务/数据/路由 key 不动，仅 UI 文案）；新增 `知乎搜索`、`GEO`，共 5 子页。

### D2. 知乎搜索 数据中心页（镜像知乎问题）
- 新组件 `ZhihuSearchAnalyticsPage.vue`（仿 `ZhihuRankingPage.vue`）：
  - KPI：监测关键词数 / 平均命中数 / 平均首位排名 / 异动关键词数
  - 命中数·首位排名 折线趋势
  - 关键词列表：关键词 / 任务·品牌 / 命中数 / 首位排名 / 变化 / 下钻
  - 下钻：该关键词 Top10 结果 + 7 天趋势（复用既有知乎搜索详情卡）
- 后端：新增 `GET /api/monitor/history/zhihu-search?range=1d|7d|30d`，仿 `zhihu-ranking` 聚合 `zhihu_search` 任务结果。

### D3. GEO 数据中心页（新设计）
- 新组件 `GeoAnalyticsPage.vue`：
  - KPI：监测关键词数 / 平均曝光率 / 平均排名 / 高权重信源数
  - **关键词 × AI 平台矩阵**（行=关键词，列=通义/豆包/DeepSeek/Kimi/元宝）：单元格 = **名次 + 颜色**（绿=被推荐+排名、橙=靠后/中性、红=负面、灰=未提及）；点单元格下钻该平台**回答原文 + 引用信源**。尽量复用 `GeoRankHeatmap.vue`。
  - **高权重信源榜**：按 weight 排序（域名/规范信源名 + 类型 + 权重分 + 被引数 + 覆盖平台数），支持「选中 → 去引流中心铺源」；复用 `GeoSourceList.vue` 思路。
  - 曝光率/平均排名趋势（1d/7d/30d），复用 `GeoTrend.vue`。
- 后端：新增 `GET /api/monitor/history/geo?range=` → 返回矩阵 cells（keyword×platform：mentioned/rank/sentiment）+ 高权重信源榜 + KPI + 趋势。聚合 `geo_cells` / `geo_citations`。

### D4. 高权重信源（新数据 + 算法）
- **规范信源（canonical source）**：建立 `host/子域前缀 → {canonical_key, 显示名, source_type}` 映射（扩展 `classify.py` 现有规则表）。
  - 默认：按主域名 eTLD+1 合并（`zhihu.com`/`zhuanlan.zhihu.com`/`www.zhihu.com` → `知乎`）。
  - 例外（按产品拆）：`baijiahao.baidu.com`→百家号、`baike.baidu.com`→百度百科、`zhidao.baidu.com`→百度知道、`tieba.baidu.com`→贴吧、`mp.weixin.qq.com`→微信公众号。
- **权重**：`weight = 被引频次 × 覆盖平台数 × authority(source_type)`。`authority` 为 `source_type` → 基数的小表（权威媒体/知乎等高，个人博客/其他低）。
- 数据：在聚合层按 `canonical_key` group by 计算 weight / 被引数 / 覆盖平台数 / 覆盖关键词数（`geo_citations` 可加 `canonical_key` 派生列或聚合时计算）。

### D5. 首页卡片
- `HomeView.vue`：4→6 卡，**3×2 网格**（`lg:grid-cols-3`）。
- 新增 `ZhihuSearchCard.vue`（命中数/首位排名 + 迷你趋势 + 异动徽标）、`GeoCard.vue`（AI 曝光率 + 最佳/最弱平台 + 迷你趋势 + 异动徽标），沿用现有卡片骨架；点击跳监控中心对应 tab（`zhihu_search` / `geo`）。
- `/api/monitor/summary` 扩展返回 `zhihu_search` / `geo` 摘要。

### 测试
- 前端：新组件渲染（KPI/矩阵/信源榜/卡片）的快照或基本断言；空数据态。
- 后端：新增聚合端点单测（含 canonical source 合并：`*.zhihu.com` 归一、百度系拆分；weight 计算）。
- 手测：数据中心 5 子页可切换、改名生效；首页 6 卡布局正确、点击跳转正确。

---

## 6. 跨流约定

- **发布**：走 PR 流程（push 分支 + `gh pr create`，不直推 main）。版本 bump 用 `release.py` 一键管 6 处；`CHANGELOG.md` 必加 entry（否则 CI `extract_changelog` 卡）。
- **既有坑规避**：前端加依赖用 `npm`（非 pnpm）；发版前 `npx npm@10 ci` 验证；`vue-tsc` strict；Win CI 仅 ASCII print；PyInstaller spec 数据文件 catch-all。
- **DB 迁移**：Stream B（`videos` 加列）、Stream D（信源派生）按现有 monitor.db schema 版本升级方式处理。

## 7. 不做（YAGNI / Out of scope）
- 夸克（Quark）GEO provider（设计有、代码缺）——本批不补。
- 全局「我的品牌」统一设置（Stream B 用任务级字段）。
- always-on-bottom 真·置底（用 off-screen 替代）。
- headless RPA（用 off-screen 替代）。

## 8. 实现确认点（planning 时 pin 死）
- A：「平台评论」监控前端的确切组件名及是否已有进度条组件。
- B：抽取 `fetch_video_comments` 的函数签名；三平台在 mining context 下抓评论的端点/签名复用方式（B 站 WBI、抖音 XHR 拦截 vs 评论 API、快手 in-page fetch）。
- C：CDP `Browser.setWindowBounds` 在 patchright persistent context 的可用性与多屏坐标处理。
- D：现有 `history/zhihu-ranking` 与 `summary` 聚合实现细节，照搬到 zhihu-search / geo / 新卡片。

## 9. 建议实现顺序（4 个独立 plan/PR）
1. **A**（小、纯后端+小前端，独立可发）
2. **C**（小、纯后端 infra，独立可发）
3. **B**（中、mining 后端 + 抽取重构 + DB 迁移）
4. **D**（大、前端 5 页/2 卡 + 多个后端聚合端点 + 信源算法）
