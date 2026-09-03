# 采集模块改走 TikHub 付费搜索 —— 设计方案

- 创建：2026-09-01
- 状态：设计已拍板（§3）；实现计划：`docs/superpowers/plans/2026-09-01-mining-tikhub-search.md`
- 关联：
  - 复用监测模块的 TikHub 集成（`csm_core/monitor/tikhub/client.py`、`tikhub` keyring key、`monitor.tikhub_base_url`）
  - 前置设计：`2026-07-06-tikhub-api-scraping-mode-design.md`（监测侧，**当时明确把 mining 划出范围**；本方案把 mining 纳入）

## 1. 背景与目标

现在的采集（关键词 → 找视频）全部走**本地浏览器**（Patchright + 登录 cookie + X-Bogus 签名 + 验证码软着陆），**同时采集多个平台会触发风控**（抖音尤甚），且依赖每个平台维持登录态。用户已开通 TikHub 付费聚合 API，希望**把采集的"找视频"这一步改走 TikHub**：免登录、免并发风控。

**目标**：只替换"怎么拿到那批候选视频"，拿到之后的全局去重、已评论反查、品牌评论预过滤、候选池、AI 生成、审核、腾讯文档同步**全部复用、零改动**。

## 2. 范围

**纳入**：抖音 / B站 / 快手 三平台的**关键词视频搜索**改走 TikHub；一个采集侧数据源开关（默认 TikHub，浏览器保留为手动兜底）。

**排除**：监测模块的 `data_source_mode`（保持独立，不动）；TikHub 的用户搜索 / 直播搜索 / 音乐搜索等；本地浏览器采集适配器（**零改动保留**，作为兜底）。

## 3. 决策记录（2026-09-01 拍板）

| # | 决策 |
|---|---|
| D1 | 三平台**全部**走 TikHub（含快手、B站），彻底替换浏览器为默认路径 |
| D2 | 保留浏览器采集作为**手动兜底开关**（TikHub 宕机 / 额度耗尽时一键切回），仿监测 `data_source_mode` |
| D3 | 采集默认条数：每平台 **50**，硬顶 **80** |
| D4 | 复用现有 `tikhub` keyring key + `monitor.tikhub_base_url`，不单独再配 |
| D5 | 失败不回退（对齐监测 D2）：TikHub 报错 = 该平台 `failed` + 通知，绝不偷偷回退浏览器 |

## 4. 已实测确认的外部事实（用用户 token 各打 1 发，2026-09-01）

> 官方文档页半残（SPA/404），以下端点/参数/返回结构均来自**下载 openapi.json + 真实响应实测**，不是文档猜测。三发调用均 HTTP 200 + body `code==200`。

### 4.1 端点与请求参数

| 平台 | 端点 | 方法 | 关键参数 | 翻页游标 |
|---|---|---|---|---|
| 抖音 | `/api/v1/douyin/search/fetch_video_search_v2` | **POST**（json body） | `keyword`；`sort_type`(0综合/1最多点赞/2最新)；`publish_time`(0不限/1一天/7一周/**180**半年)；`content_type`(0全部/1视频/2图片/3文章)；`filter_duration`(0/0-1/1-5/5-10000)；`cursor`(int,默认0) | `cursor` + 响应里的 `search_id`/`backtrace` |
| B站 | `/api/v1/bilibili/web/fetch_general_search` | GET | `keyword`；`order`(必填,字符串：totalrank综合/pubdate最新/click最多播放/dm最多弹幕/stow最多收藏——需实现期用一发确认取值)；`page`；`page_size`；`pubtime_begin_s`/`pubtime_end_s`(10位秒级时间戳,日期区间)；`duration` | `page` 递增 |
| 快手 | `/api/v1/kuaishou/app/search_video_v2` | GET | `keyword`(必填)；`pcursor` | `pcursor`（主判据：缺失/空/`"no_more"`/与上页相同即停；`recoPcursor` **不作**终止信号，见 §7 R6） |

**筛选映射**（图二 UI → TikHub 参数）：
- 抖音：发布时间/排序/内容类型 **1:1 下推**（UI 的 182 → API 的 180）；端点虽支持 `filter_duration`，但 UI 无时长档位（`DouyinFilters` 无该字段），不下推。
- B站：排序 + **发布日期区间**（`pubtime_begin_s/end_s`），与现有 B站 UI 一致；`duration` 同上不下推。
- 快手：TikHub 无服务端筛选 → 时间条件**本地后过滤 + 自动补页**（与现状一致）。

### 4.2 响应结构（视频列表路径 + 字段，实测钉死；fixture 已落 `sidecar/tests/tikhub/fixtures/tikhub_search_{douyin,bilibili,kuaishou}.json`）

**抖音** `data.business_data[]`（本发 8 项，`type=="1"` 为视频卡共 7 项，`type=="66668"` 为其它/推荐需跳过）→ 视频在 `item["data"]["aweme_info"]`，**与现有浏览器 XHR 的 aweme_info 同形**：
- `aweme_id`、`desc`、`author.nickname`/`author.uid`、`statistics.{digg_count,comment_count,play_count,share_count}`、`create_time`(unix秒)、`video.duration`(ms)、`share_url`、`aweme_type`(0=视频)、`images`(非空=图文)。
- → **抖音 normalizer 直接借用现有 `douyin_search.py:_extract_cards` 的逻辑**（同一 aweme_info 结构）。

**B站** 列表在 `data.data.result[]`（外层 `data` 是 TikHub 包装，内层 `data` 是 B 站原生 `{seid,page,pagesize,numResults,numPages,result}`），本发 20 项，`type=="video"` 字段直接可用：
- `bvid`、`aid`、`arcurl`/`url`、`title`(含 `<em class="keyword">` 高亮标签，**需 strip**)、`author`、`mid`、`play`、`like`、`favorites`、`danmaku`、`review`、`pubdate`(unix秒)、`duration`("11:28" 字符串,需转秒)、`pic`(封面)、`typename`、`tag`、`description`。

**快手** `data.mixFeeds[]`（本发 22 项，`itemType==5` 为视频共 19 项，`itemType==28` 为相关搜索/其它需跳过）→ `item["feed"]` flat 字段：
- `photo_id`、`caption`、`user_name`、`user_id`、`view_count`、`like_count`、`comment_count`、`share_count`、`collect_count`、`duration`(ms)、`timestamp`(发布,ms)、`cover_thumbnail_urls`、`main_mv_urls`、`kwaiId`。
- 翻页：`data.pcursor`（"1"→下一页；缺失/空/"no_more"/与上页相同即停）。同一响应里 `recoPcursor=="no_more"` 与 `pcursor="1"` 并存，判定 `recoPcursor` 是推荐流游标、**不作终止信号**（同族评论端点末页 `pcursor="no_more"` 佐证 "no_more" 是 pcursor 一族的终值）。

## 5. 架构设计

### 5.1 数据源开关（config + 分派）

- `csm_core/config.py` → `AppConfig` 顶层新增（代码库没有 `MiningConfig` 子模型，mining 字段与 `mining_prefilter_*` 一样直接挂在 `AppConfig` 上）：
  ```python
  mining_data_source_mode: Literal["tikhub_api", "local"] = "tikhub_api"  # 默认 TikHub
  ```
  （pydantic 默认值，无 DB 列，无需迁移。）
- 分派：`runner.get_adapter(platform, mode)`，`run()` 每次现读 `mining_data_source_mode`：
  - `tikhub_api` → 新的 TikHub 搜索适配器（本方案）；
  - `local` → 现有浏览器适配器（**零改动**）。
- TikHub 模式**天然绕过登录检查 + 不并发风控限速**（无 cookie/无浏览器）；额度耗尽走现有进程级 402 余额闩（`tikhub/client.py`），本轮短路 + 聚合通知。

### 5.2 客户端改造（`csm_core/monitor/tikhub/client.py`）

- 现只有 `get()`；抖音搜索是 **POST** → 加 `post(path, json_body) -> dict`，复用同一套：`Authorization: Bearer`、HTTP≠200/body code≠200 映射中文错误、402 置余额闩、`_redact()` 抹 key、非法 JSON 兜底。
- **搜索重试**（区别于评论适配器"不重试"）：官方标注搜索端点偶发失败（失败率 <5%），**同参数重试 1–3 次**。搜索是只读、无副作用，重试的重复计费风险可接受；封装成搜索专用分页里的每页重试。

### 5.3 搜索适配器（新增 `csm_core/mining/platforms/tikhub_search.py` + `tikhub_normalize.py`）

- 一个通用 `TikHubSearchAdapter` + 三个 `SearchSpec`（platform / method / path / first_request / next_request / normalize），实现现有 mining `SearchAdapter` Protocol：
  `search(keyword, target_count, on_card, on_progress, cancel_event, max_attempts=None, filters=None) -> SearchOutcome`。
- 流程：`first_request(keyword, filters[platform])` 下推筛选 → 调 client（抖音 POST / B站快手 GET，每页失败重试 ≤3）→ `next_request(prev, raw)` 翻页（各自游标 + `MAX_PAGES` 硬闸）→ `normalize(raw, filters)` 成现有 `VideoCard` → `on_card`（带 `rank_in_search`）+ `on_progress`。
- normalize 复用：**抖音借用 `_extract_cards`**；B站/快手新写小 normalizer（§4.2 字段已钉）。B站 title 去 `<em>` 标签；duration 字符串转秒。
- **适配器层永不异常穿透**（normalize / next_request 的异常按页级错误处理；归一化模块只对实测到的畸形结构兜底）：**首页**失败（重试耗尽 / 解析异常）→ `status="failed"`；**已发出 ≥1 张卡后**的后续页失败 → `status="done"` + note（已入库候选不因翻页失败被记失败——runner 只对 done 跑品牌预筛）；绝不回退浏览器；`cancel_event` 命中 → `cancelled`。终止判据（按序）：达 target / 整页都是重复卡（cards 非空且 0 张新卡，游标疑似卡住）/ 无下一页 / `MAX_PAGES` 硬闸；整页被本地过滤为空**不**停（快手日期区间靠翻页补偿）。
- 快手/B站的本地时间后过滤沿用现状（快手无服务端时间参数）。

### 5.4 成本护栏

- 每平台 `target_count` 默认 50、**硬顶 80**（clamp）；`max_pages` 硬闸（防跑飞计费）。
- 成本量级：搜索 $0.01/次、每次约 6–14 条 → 单平台 50 条 ≈ 4–8 次 ≈ $0.04–0.08；一次三平台 ≈ **$0.15–0.3**（含偶发重试）。
- UI 成本提示：明示按次计费 + 高频采集会显著增加费用。

### 5.5 UI（`StartJobModal` / `PlatformPickerCard` / 设置页）

- 采集设置区（或任务弹窗顶部）：数据源开关 TikHub（默认）⇄ 浏览器兜底；复用 `tikhub` key「已配置」状态。
- `PlatformPickerCard`：TikHub 模式把「已登录/未登录」换成「TikHub 就绪」（不需登录、不弹登录）；浏览器兜底模式保留登录态 + 登录按钮。
- 图二筛选块：抖音/B站保留（下推）；快手时间标「本地过滤」（同现状）。

## 6. 测试策略

- **Fixture 回归**：3 平台真实搜索响应落 `sidecar/tests/tikhub/fixtures/`（本次已抓到）→ normalizer 单测：字段路径、抖音卡型过滤（type==1 / 跳过 66668）、快手 itemType==5 过滤、B站 title 去 `<em>`、duration 转秒、图文（抖音 content_type=2 / images 非空）。
- **client 单测**：新增 `post()` 鉴权/错误映射/402 闩；搜索重试（失败重试 1–3 次后成功 / 耗尽抛错）。
- **适配器单测**：分页游标（抖音 cursor / B站 page / 快手 pcursor no_more 停）、`max_pages` 硬闸、target clamp ≤80、页失败→failed 不返残缺、cancel。
- **分派单测**：`data_source_mode=="tikhub_api"` 选 TikHub 适配器、`"local"` 选浏览器适配器。
- ⚠️ sidecar 测试不进默认 CI，必须显式 `pytest sidecar/tests/`。

## 7. 风险与未决

- **R1 B站 `order` 取值（已解决）**：实测 `order=totalrank` 通过（HTTP 200，20 条）；取值沿用 `bilibili_search._VALID_ORDERS`（totalrank/click/pubdate/dm/stow，B 站 web 原生），未知值回落 totalrank。
- **R2 抖音翻页游标（已解决）**：实测游标在 `data.business_config`：`has_more`(1=有下页)、`next_page.cursor`、`next_page.search_id`、`backtrace`；下一页 body 回传这三个字段，`has_more != 1` 即停。
- **R3 TikHub 单点故障**：宕机=三平台同黑（D5 不回退）；缓解=一键切回浏览器兜底（D2 强调该出口）。
- **R4 成本失控**：靠 §5.4 每平台上限 + max_pages + 频率提示 + 402 余额闩共同兜底。
- **R5 快手 mixFeeds 噪音**：`itemType!=5` 的相关搜索/运营卡需过滤（§4.2 已确认判据）。
- **R6 快手翻页语义未真机验证**：实现期 TikHub 快手端点处于临时故障（连首页都 400「Request failed. Please retry … won't be charged」，同 `feedback_tikhub_transient_400_outage_diagnosis` 签名），无法验证 `pcursor="1"` 能否取到第 2 页。已按最安全口径实现（pcursor 主判据 + 游标不动点闸 + 后页失败降 done）：最坏情况是第 2 页白请求一次（该类失败不计费），而 recoPcursor 主判据的最坏情况是永久单页且完全静默。首次真机采集后看日志里每页 pcursor 是否 "1"→"2" 推进即可确认。

## 8. 不做（YAGNI）

- 不动监测模块 `data_source_mode`（两模块各自独立开关）。
- 不做 TikHub 用户/直播/音乐搜索。
- 快手不强求服务端筛选（本地后过滤足够）。
- 不删浏览器采集代码（留作兜底）。
