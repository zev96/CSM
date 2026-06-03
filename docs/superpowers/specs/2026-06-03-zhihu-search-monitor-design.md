# 知乎搜索排名监控 · 设计

- 状态：已与用户对齐，待生成实施计划
- 日期：2026-06-03
- 工作树：`.claude/worktrees/recursing-nobel-2de735`（分支 `claude/recursing-nobel-2de735`）
- 相关代码栈：Tauri shell + Vue 前端 + Python sidecar，沿用 `csm_core/monitor/` 现有平台 adapter 范式
- 一句话：把现有「百度关键词排名」那套「关键词 → 品牌词在前 N 的排名」模式，换成**知乎官方搜索 API** 实现，无爬虫/cookie/验证码/风控。

## 1. 目标与边界

在「监控中心」新增一种监控类型 `zhihu_search`：

- 用户给定**一到多个搜索关键词** + **一个目标品牌词**（可带别名）
- 对每个关键词调用知乎官方搜索 API（`GET /api/v1/content/zhihu_search`，Bearer 鉴权），拿**前 10 条**结果
- 对每条结果，在 `Title + ContentText（摘要）+ AuthorName` 上大小写不敏感匹配品牌词/别名
- 命中 → 记 1-based 排名；记录每个关键词的「首个命中位置 + 命中条数」，以及完整前 10 快照
- 入历史库、画趋势、走现有告警（排名掉出）逻辑
- 完全复用 `monitor_loop` 的泛型调度 / SSE / 结果持久化，**不碰存储 schema**

**非目标（明确不做）：**

- 不做「自有内容精确匹配」模式（用户已选「品牌词命中」语义）
- 不接入文档里另外 3 个兄弟 API（全网搜索 `global_search` / 直答 / 热榜 `hot_list`）—— 留作未来，见 §9
- 不做分页（API 无分页，`HasMore` 恒 false，`Count` 上限 10）
- **默认**只匹配 API 直接返回的标题/摘要/作者；**全文级匹配是可选 opt-in 增强**（默认关，分阶段交付，见 §5.4 与 §9）—— 用户已确认「先这样做，可行再加全文」
- 不做持久化配额计数表 / UI 配额条（用户已选「仅优雅处理 30001」）
- 设置页不加「测试连通」按钮（用户已选）
- 不与现有 `zhihu_question`（问题维度监控）合并 —— 两者语义不同，各自独立

## 2. 关键决策（已与用户对齐）

| 维度 | 决策 |
|---|---|
| 监控语义 | **品牌词命中排名**：给定关键词，看品牌/产品名是否出现在前 10 结果，记首个命中位置 + 命中条数 |
| 匹配字段（默认）| `Title` + `ContentText`（摘要）+ `AuthorName`，大小写不敏感子串；记录命中字段 |
| 全文级匹配 | **可选 opt-in**（`config.match_full_text`，默认关）：开后对前 10 逐条去 zhihu.com 抓正文再匹配，best-effort 抓不到回退摘要；复用 `zhihu_question` 的 cookie/抓取设施。见 §5.4 |
| 数据来源 | **默认路径**走知乎官方 API（结构化 JSON，httpx + Bearer，**无爬虫/cookie/验证码/风控**）；全文匹配开关打开后才引入 zhihu.com 正文抓取（curl_cffi + cookie）|
| 凭证 | 全局单个 Access Secret，走现有 keyring 基建（`provider="zhihu"`），非按任务配置 |
| 配额（1000/天）| 仅**优雅处理 30001**（频率/配额超限）：标该关键词「限流」+ 熔断退避，不做持久化计数表 |
| 设置页测试按钮 | 不加；只做保存 + 已配置/未配置状态 |
| 任务粒度 | 一个 task = N 个关键词 × 1 个品牌词（仿 baidu_keyword）；批量导入复用现有机制 |
| 调度 | 复用现有 `SCHEDULE_OPTIONS`（manual / 每 N 小时 / 每天 / 每周）|
| 排名约定 | 复用 1-based；`MonitorResult.rank` = 所有关键词中**最优首个命中位置**，-1 = 全未命中 |
| 存储 | 仅写 `monitor_results.metric_json`（JSON），**不加任何表、不 bump schema** |

## 3. API 摘要（已逐字核对官方文档）

- 文档：<https://developer.zhihu.com/docs?key=zhihu_search>

| 项 | 值 |
|---|---|
| Endpoint | `GET https://developer.zhihu.com/api/v1/content/zhihu_search` |
| 鉴权 Header | `Authorization: Bearer <access_secret>` · `X-Request-Timestamp: <秒级 Unix 时间戳>` · `Content-Type: application/json` |
| Query 参数 | `Query`(String, 必填, 非空) · `Count`(Int32, 选填, 默认 10 / 上限 10；`<=0` 回退 10，`>10` 截断 10) |
| 响应外层 | `Code`(0=成功) · `Message` · `Data` |
| `Data` | `HasMore`(Bool, 恒 false) · `SearchHashId`(String) · `Items`(Array) · `EmptyReason`(String, 选填) |
| `Item` | `Title` · `ContentType`(Article/Answer/…) · `ContentID` · `ContentText`(摘要) · `Url`(带 utm) · `CommentCount` · `VoteUpCount` · `AuthorName` · `AuthorAvatar` · `AuthorBadge` · `AuthorBadgeText` · `EditTime`(时间戳) · `CommentInfoList`(选填) · `AuthorityLevel` · `RankingScore`(Float) |
| 错误码 | `0` 成功 · `10001` 参数错 · `20001` 鉴权失败 · `30001` 频率限制 · `90001` 内部错误 |
| 配额 | 1000 次/天（每个关键词 = 1 次调用）|

**Curl 示例（官方）：**
```bash
curl -G 'https://developer.zhihu.com/api/v1/content/zhihu_search' \
  --data-urlencode 'Query=怎么理解rave文化' \
  -d 'Count=5' \
  -H 'Authorization: Bearer <your_access_secret>' \
  -H "X-Request-Timestamp: $(date +%s)"
```

**注意点：**
- `X-Request-Timestamp` 是秒级且服务端会校验 → **系统时钟偏差过大会触发 `20001 鉴权失败`**（写进文档 + 错误提示）。
- `30001` 同时覆盖「每秒频率超限」和「每日 1000 配额用尽」两种情况——文档不区分，都按「限流」处理即满足「优雅处理 30001」。
- 官方 search 示例未带 `Content-Type`，但参数表把它列为固定值；我们三个 header 都带，无害。

## 4. 架构与模块边界

### 4.1 后端（Python）—— 默认（摘要匹配）仅 3 处

```
csm_core/monitor/
├── base.py                       ← TaskType Literal 加 "zhihu_search"
└── platforms/
    ├── __init__.py               ← import + 注册 ZHIHU_SEARCH 进 ALL
    ├── zhihu_search.py           ← 新增：ZhihuSearchAdapter + zhihu_search_api()
    └── zhihu_content.py          ← 仅「全文匹配」阶段新增（§5.4）：共享正文抓取 helper

# 完全不动：
#   monitor_loop.py / monitor_service.py / storage.py / rate_limit.py
#   routes/monitor.py（泛型路由已覆盖任意 task type）
#   monitor_lifecycle.py（本 adapter 无需 apply_settings，pacer/breaker 用默认）
```

> 默认范围（PR #1/#2）后端仅 `base.py` + `zhihu_search.py` + `__init__.py` 三处。可选全文匹配（PR #3）再加 `zhihu_content.py` 共享 helper（从 `zhihu_question` 抽取 `_strip_tags` / CookieStore 用法）。

`monitor_loop` 已确认会用渐进降级签名调用 `adapter.fetch(task, progress_cb=…, cancel_token=…, resume_from=…)`，并泛型持久化 `MonitorResult` + 推 SSE。新 adapter 用完整签名即可即插即用。

### 4.2 前端（Vue）

```
frontend/src/
├── utils/monitor-types.ts                    ← +ZhihuSearchTaskConfig 接口
├── components/monitor/
│   ├── AddTaskModal.vue                       ← +zhihu_search 类型分支与表单
│   └── ZhihuSearchModule.vue                  ← 新增（仿 ZhihuMonitorModule 列表/详情）
├── views/MonitorView.vue                      ← +「知乎搜索」Tab 挂载
└── views/SettingsView.vue                     ← providers 列表 +「知乎开放平台」一项
```

### 4.3 Adapter 内部结构（`zhihu_search.py`）

```python
ZHIHU_SEARCH_URL = "https://developer.zhihu.com/api/v1/content/zhihu_search"

def zhihu_search_api(query: str, count: int, secret: str,
                     *, timeout: float = 20.0) -> dict:
    """纯函数：发一次请求，返回 {code, message, data, http_status, error}。
    httpx.get + Bearer + X-Request-Timestamp(int(time.time()))。
    便于 mock httpx 单测，不碰任何全局状态。"""

def match_brand(text: str, brands: list[str]) -> str | None:
    """大小写不敏感找首个出现的品牌词（复用 baidu_keyword 同款逻辑）。"""

class ZhihuSearchAdapter:
    platform = "zhihu_search"
    def __init__(self):
        self._pacer = get_pacer("zhihu_search")      # 关键词间默认 ~1s 间隔
        self._breaker = get_breaker("zhihu_search")   # 连续失败 → 熔断
    def fetch(self, task, *, progress_cb=None, cancel_token=None, resume_from=0) -> MonitorResult:
        ...
```

`fetch()` 流程：

1. `_breaker.allow()` —— 熔断检查；开路则直接返回 `status="risk_control"`
2. 读 `config.search_keywords` / `config.target_brand`(+`brand_aliases`) / `config.count`；任一缺失 → `status="failed"`，提示
3. `read_api_key("zhihu")` 取 Access Secret；为空 → `status="error"`，提示「请到设置页配置知乎 Access Secret」
4. `maybe_cancel(cancel_token)` + `progress_cb(0, N)` 先推总数
5. 逐关键词循环（关键词之间 `_pacer.wait()` + `maybe_cancel`）：
   - `zhihu_search_api(kw, count, secret)`
   - 按 `Code` / `http_status` 分流：
     - `Code==0` → 解析 `Data.Items[]`，对每条先在标题/摘要/作者匹配品牌词；若 `config.match_full_text` 为真且未命中，再 best-effort 抓正文匹配（§5.4）。算 `first_rank` + `matched_count`，拼 `results[]`；`Data.EmptyReason` 透传
     - `30001` → 该关键词标 `limited`（`api_code=30001`），`self._breaker.record_failure()`；若熔断中途开路，剩余关键词标 `risk_control`
     - `20001` → 整 task `status="error"`，消息含「Access Secret 错误或系统时钟偏差过大」，**立即中止**（再调也会失败）
     - `10001`/`90001`/非 JSON/HTTP≥400 → 该关键词标 `fetch_error`，继续下一个
   - `progress_cb(i+1, N)`
6. 聚合 → `metric`（见 §5.3），`MonitorResult.rank = best_first_rank`
7. 全程成功 `record_success()`，否则 `record_failure()`

## 5. 数据模型

### 5.1 `TaskType` 扩展（`base.py`）

```python
TaskType = Literal[
    "zhihu_question",
    "zhihu_search",        # ← 新增
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
    "baidu_keyword",
    "geo_query",
]
```

### 5.2 `MonitorTask`

- `config`：
```jsonc
{
  "search_keywords": ["扫地机器人推荐", "宠物吸尘器"],  // 多关键词，每个跑一次搜索
  "target_brand": "示例品牌",                          // 单品牌词
  "brand_aliases": ["ExampleBrand", "EB"],            // 可选别名，与 target_brand 一起参与匹配
  "count": 10,                                         // 固定 10（不在表单暴露）
  "match_full_text": false                             // 可选：开后对前 10 抓正文再匹配（§5.4），默认关
}
```
- **单一真相源是 `config.search_keywords`**。`target_url` 在**前端 `AddTaskModal` 提交时**从 `search_keywords[0]` 派生为可点击的知乎搜索 URL：`https://www.zhihu.com/search?type=content&q=<urlencoded(第一个关键词)>`，仅用于展示/跳转。在前端派生是为了让后端路由保持零改动（§4.1）；写计划时核对 baidu 是否也在前端派生，若 baidu 在路由层派生则二选一统一，不要两处都写。
- `schedule_cron` 复用现有 `SCHEDULE_OPTIONS`。

### 5.3 `MonitorResult` 与 `metric`

- `rank` = `best_first_rank`（所有关键词里最优的首个命中位置；-1 = 全未命中）→ 现有 sparkline / 排名掉出告警直接复用。
- `status`：正常 `ok`；config 缺失 `failed`；鉴权失败 `error`；30001 限流且熔断开路 `risk_control`。

```jsonc
{
  "source": "zhihu_openapi",
  "target_brand": "示例品牌",
  "brand_aliases": ["ExampleBrand"],
  "search_keywords": ["扫地机器人推荐", "宠物吸尘器"],
  "count": 10,
  "keywords": [
    {
      "keyword": "扫地机器人推荐",
      "search_hash_id": "1234567890",
      "results": [
        {
          "rank": 1,
          "title": "2026 扫地机器人怎么选",
          "content_type": "Article",
          "content_id": "123456789",
          "url": "https://zhuanlan.zhihu.com/p/123456789?utm_...",
          "voteup_count": 128,
          "comment_count": 15,
          "author_name": "张三",
          "authority_level": "2",
          "ranking_score": 0.98,
          "edit_time": 1710000000,
          "matches_brand": false,
          "matched_brand": null,
          "matched_field": null,            // "title" | "excerpt" | "author" | "fulltext"
          "fulltext_status": "disabled",    // disabled|skipped|matched|fetched_no_match|fetch_failed|no_cookie
          "excerpt": "…前 160 字摘要…"
        }
        // … 最多 10 条
      ],
      "matched_count": 1,
      "first_rank": 3,
      "result_count": 10,
      "empty_reason": null,
      "api_code": 0,
      "fetch_error": null
    }
  ],
  "total_keywords": 2,
  "matched_keywords": 1,
  "total_matches": 1,
  "best_first_rank": 3
}
```

边界处理：
- 单关键词失败（fetch_error / 30001）不拖垮整 task —— 标记后继续其余关键词。
- 只存 160 字 `excerpt`，不存全文（即使开全文匹配，正文也只用于即时匹配、不落库），避免 result 行膨胀。
- 跨平台 `MonitorResult.rank` 语义一致，复用现有告警与历史趋势。

### 5.4 可选：全文级匹配（分阶段增强，默认关闭）

用户反馈：摘要版先上，**可行再加全文级匹配**。因此设计为**按任务 opt-in 开关** `config.match_full_text`（默认 `false`）+ **best-effort**（抓不到全文就回退摘要，绝不让全文抓取拖垮整 task）。

**为什么独立 + 默认关：** 全文匹配要对前 10 逐条去 `zhihu.com` 抓正文，重新引入了官方 API 本来帮我们绕开的 cookie / 反爬 / 延迟成本。默认路径必须保持「纯官方 API、零反爬」；需要更高召回的用户再开。

**实现（复用现有 `zhihu_question` 设施，不重造轮子）：**
- 抽共享 helper `zhihu_content.fetch_text(content_type, content_id, *, cookie_store) -> str | None`：
  - `ContentType=="Article"` → curl_cffi GET `https://www.zhihu.com/api/v4/articles/{content_id}?include=content` → 取 `content`(HTML) → `_strip_tags`
  - `ContentType=="Answer"` → curl_cffi GET `https://www.zhihu.com/api/v4/answers/{content_id}?include=content`
  - 其它类型（Question 等）→ 返回 `None`（回退摘要）
  - `impersonate="chrome120"` + 复用 `zhihu_question` 同一知乎 Cookie 池（`CookieStore("zhihu_question")`）+ UA 池
  - 任意失败（4xx / 反爬 HTML / 非 JSON / 超时）→ `None`，**不重试、不开浏览器**（10 条全开浏览器太重）
- adapter 在 `match_full_text=True` 时，对每条结果：先 `match_brand(标题/摘要/作者)`；**未命中**再 `fetch_text()` 拿正文匹配；命中则 `matched_field="fulltext"`，`fulltext_status="matched"`。
- 节流：全文抓取走独立 pacer `zhihu_search:content`，避免对 zhihu.com 秒级连发触发反爬。

**前置条件：** 需在 Cookie 管理里配置知乎 cookie（与 `zhihu_question` 共用同一池）。无 cookie 时全文抓取大概率失败 → 自动回退摘要，并标 `fulltext_status="no_cookie"`，UI 提示「开启全文匹配需配置知乎 Cookie」。

**为什么不影响默认范围的「3 处改动」：** `match_full_text` 默认 false，PR #1/#2 的 adapter 走纯摘要路径；`zhihu_content.py` 只在 PR #3 引入，且 import 是惰性的（开关关闭时不 import、不碰 cookie）。

## 6. 凭证配置（Access Secret）

- 走**现有 keyring 基建**（`/api/keyring/{provider}` 已是泛型，后端 `read_api_key("zhihu")` 直接取）。
- `SettingsView.vue` 的 providers 列表加一条：`{ key: "zhihu", label: "知乎开放平台 Access Secret", … }`，复用现有保存/掩码/「已配置/未配置」状态显示。
- **不加测试按钮**（用户已选）：保存即写 keyring；连通性留待首次真正跑任务时暴露。
- 全局单凭证（一个开发者账号一个 secret），非按任务。

## 7. 前端 UI

### 7.1 AddTaskModal 知乎搜索分支

字段：
- 任务名称（必填 → `MonitorTask.name`）
- 搜索关键词（必填，多行 → `config.search_keywords[]`）
- 目标品牌词（必填 → `config.target_brand`）
- 品牌别名（可选，多行/逗号 → `config.brand_aliases[]`）
- 调度（复用 `SCHEDULE_OPTIONS` 组件）
- 全文级匹配开关（可选，默认关 → `config.match_full_text`；PR #3 才出现，开关旁注「需配置知乎 Cookie」）
- 提交时前端派生 `target_url`（见 §5.2）

### 7.2 ZhihuSearchModule.vue（新）

仿 `ZhihuMonitorModule.vue` 的左侧任务列表 + 右侧详情布局。详情自上而下：
1. **任务标头**：知乎搜索 URL · 上次检查 · 状态（正常/限流/鉴权失败）· 操作（立即执行 / 编辑 / 删除）
2. **趋势卡**：近 N 天，双线（命中关键词数 + 最优首个排名）
3. **每个关键词一张卡**：前 10 列表，列 `排名 | 标题 | 类型 | 作者 | 赞同 | 命中?`；命中行高亮 + Pill `命中: <matched_brand>(<matched_field>)`；`Url` 可点（带 utm）；摘要 160 字默认折叠
4. 关键词无结果（`EmptyReason`）→ 显示「知乎无结果：<EmptyReason>」
5. 关键词限流（30001）→ 行标红 Pill「限流，稍后重试」

### 7.3 monitor-types.ts

```ts
export interface ZhihuSearchTaskConfig {
  search_keywords: string[];
  target_brand: string;
  brand_aliases: string[];
  count: number;
}
```

### 7.4 MonitorView

在现有 Tab 集合（zhihu_question / comment / baidu / geo）中加「知乎搜索」Tab，挂 `ZhihuSearchModule`。具体 Tab 结构在写计划时按 `MonitorView.vue` 现状对齐。

## 8. 测试策略

### 8.1 csm_core 单测（`tests/` 仿现有 adapter 测试）

- `test_zhihu_search_api_parse_ok` — mock httpx 返回官方示例 JSON → 解析出 1 条 Item，字段齐全
- `test_zhihu_search_api_empty` — `Items=[]` + `EmptyReason` → 透传，0 命中不报错
- `test_zhihu_search_api_30001` — `Code=30001` → 标 limited，breaker.record_failure 被调
- `test_zhihu_search_api_20001` — `Code=20001` → 整 task `status="error"`，消息含时钟提示，提前中止
- `test_zhihu_search_api_non_json` — 非 JSON / HTTP 500 → fetch_error，不崩
- `test_match_brand_fields` — 品牌词分别出现在 Title / ContentText / AuthorName → 命中 + matched_field 正确
- `test_match_brand_aliases` — 别名命中
- `test_rank_first_and_count` — 多条命中 → first_rank 取最靠前，matched_count 正确
- `test_rank_no_match` — 全不命中 → rank=-1
- `test_best_first_rank_across_keywords` — 多关键词聚合 → best_first_rank = min
- `test_missing_config` — 缺 search_keywords / target_brand → failed
- `test_missing_secret` — keyring 无 zhihu → error，提示去设置页

全文匹配（PR #3）：
- `test_fulltext_match_when_excerpt_misses` — 摘要不含品牌、正文含 → mock fetch_text 命中 → `matched_field="fulltext"`，`fulltext_status="matched"`
- `test_fulltext_fetch_fail_fallback` — fetch_text 返回 None → 回退摘要结果，`fulltext_status="fetch_failed"`，不崩
- `test_fulltext_disabled_no_fetch` — `match_full_text=false` → 绝不调 fetch_text（惰性，不碰 cookie）
- `test_fulltext_unsupported_type_skipped` — `ContentType="Question"` → 跳过全文，`fulltext_status="skipped"`

### 8.2 sidecar 单测

- `type="zhihu_search"` 的 task CRUD（建/查/改/删）走泛型路由
- dispatch：mock adapter → `MonitorResult` 正常持久化 + SSE
- keyring `provider="zhihu"` 存取

### 8.3 手动集成测试

`scripts/manual_test_zhihu_search.py`：独立调用 `ZhihuSearchAdapter.fetch()`（从 keyring 或环境变量取 secret），打印 metric JSON。验证清单：
- [ ] 真实 Access Secret + 2 个关键词 → 各拿到 ≤10 条，字段正确
- [ ] 品牌词在某关键词命中 → rank/matched_count 正确
- [ ] 不存在的品牌词 → rank=-1
- [ ] 故意用错误 secret → status=error，提示清晰
- [ ] 连发触发 30001 → 标限流，不崩

### 8.4 Release 实跑

`tauri build --release` 后：
- [ ] 设置页填 Access Secret → 保存 → 状态变「已配置」
- [ ] 建 zhihu_search 任务 → 立即执行 → 历史页看到前 10 + 命中高亮
- [ ] 改调度为每天 → 列表显示调度标签
- [ ] Access Secret 留空时建任务执行 → 明确报「请配置 Access Secret」

## 9. 上线节奏

分两个 PR（仿 baidu）：

**PR #1 — 后端 + 单测**
- `csm_core/monitor/base.py`（TaskType 扩展）
- `csm_core/monitor/platforms/zhihu_search.py`（新）
- `csm_core/monitor/platforms/__init__.py`（注册）
- `tests/test_zhihu_search.py`（单测，mock httpx）
- `CHANGELOG.md`（必加条目，release.yml 卡 extract）
- 验收：单测全绿 + `scripts/manual_test_zhihu_search.py` 跑出合法 metric

**PR #2 — 前端 + 端到端**
- `frontend/src/utils/monitor-types.ts`
- `frontend/src/components/monitor/AddTaskModal.vue`
- `frontend/src/components/monitor/ZhihuSearchModule.vue`（新）
- `frontend/src/views/MonitorView.vue`
- `frontend/src/views/SettingsView.vue`（provider 项）
- 验收：release 实跑清单全过

**PR #3 — 可选全文级匹配（用户「可行再加」）**
- `csm_core/monitor/platforms/zhihu_content.py`（新，共享正文抓取 helper）
- `csm_core/monitor/platforms/zhihu_search.py`（接入 `match_full_text` 分支 + `zhihu_search:content` pacer）
- `frontend/src/components/monitor/AddTaskModal.vue`（全文开关）+ `ZhihuSearchModule.vue`（`matched_field="fulltext"` 展示 + `fulltext_status` 提示）+ `monitor-types.ts`（+`match_full_text`）
- 单测：§8.1 全文匹配 4 项
- 验收：配置知乎 Cookie + 开开关 → 摘要漏检但正文命中的关键词能标 `fulltext`；无 Cookie → 回退摘要 + 提示
- **可独立于 PR #1/#2 评估是否真做**：默认路径已完整可用；此 PR 是纯增量增强

**未来（不在本次范围）：** 文档里的 `global_search`（全网搜索）/ 直答 / `hot_list`（热榜）共用同一 Bearer 鉴权；若要做，把 `zhihu_search_api()` 抽到一个 `zhihu/` provider 包（仿 `geo/providers/`），三个兄弟 API 平滑加入。

## 10. 已识别的风险

| 风险 | 缓解 |
|---|---|
| 前 10 上限 → 品牌排名靠后时永远「未命中」| 产品设计已接受（用户明确「限制前十也可以」）；rank=-1 即代表「不在前 10」，本身是有效信号 |
| 系统时钟偏差 → `20001 鉴权失败` | 错误提示明确点出「时钟偏差」可能；文档记录；必要时后续用响应头校时 |
| 每日 1000 配额耗尽（多任务 × 多关键词）| 30001 优雅降级 + 熔断退避；UI 标「限流」；如后续需要可再加配额计数（已预留扩展点） |
| 摘要匹配漏检（品牌只在正文深处、不在标题/摘要/作者）| 默认接受（「搜索可见性」本就看标题/摘要）；需要更高召回时开 `match_full_text`（§5.4）|
| 全文匹配触发 zhihu.com 反爬 / 需要 cookie / 拖慢任务 | 默认关；opt-in；best-effort（抓不到回退摘要，不开浏览器、不重试）；独立 pacer 节流；复用 `zhihu_question` 成熟的 cookie 池 + 软封冷却 |
| `ContentText` 被知乎截断 → 匹配不稳定 | matched_field 透出命中位置，详情页可见；漏检概率低且可接受 |
| Access Secret 误粘进别处（参考豆包把 key 粘进 Base URL 的坑）| 纯 keyring 单字段，无 Base URL 概念，风险低；设置页 label 写清楚 |
| 官方 API 字段/路径变更 | `zhihu_search_api()` 是唯一对接点 + 单测覆盖解析；变更只需改一处 |
