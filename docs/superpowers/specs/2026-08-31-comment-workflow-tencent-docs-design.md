# 多平台视频评论工作流（筛选 → AI 生成 → 审核 → 腾讯文档）— 设计方案 v2

> 状态：决策点已拍板（见 §8），仅剩 1 个待补项：腾讯文档 skill 的调用方式（§5.1）
> 涉及模块：`csm_core/mining`、`csm_core/monitor`（评论适配器复用）、`csm_core/llm`、sidecar routes、前端 MiningView
> 前置调研：腾讯文档开放平台 OpenAPI（OAuth2 授权码，access_token 30 天 / refresh_token 1 年，须后台发起，每应用 2 万次/年免费额度）

---

## 0. 现状盘点：四个环节里有三个半已有地基

| 需求环节 | 已有能力 | 缺口 |
|---|---|---|
| **1. 视频筛选** | mining 模块三平台关键词搜索、全局去重（`(platform, platform_video_id)` UNIQUE）、已评论反查（`monitor_tasks` 反查 + 采集时跳过）、**品牌评论预过滤已存在**：`comment_prefilter.py` 抓每条视频前 30 条评论，品牌词命中 ≥3 条即排除（`runner.py:159-198`） | 所有平台适配器**只支持关键词**（`platforms/_common.py:27-50`），无时间范围/内容类型/排序参数；预过滤参数与需求不一致（改为前 20 条、命中 1 条即排除） |
| **2. AI 评论生成** | `mining_ai_service` 已有 AI 速览（`summarize_video`，缓存到 `videos.ai_summary`）+ AI 建议评论（`suggest_comment`）；评论模板库 `comment_templates`（哈希去重、标签、使用计数、发出自动入库）；盖楼已建模（`video_comments.tier`）；评论带图已建模（`image_ids_json`，最多 9 张） | 生成不是「模板 × 视频分析 → 改写」，而是自由生成；无去 AI 味约束（`scoring/ai_flavor.py` 的确定性评分器存在但未接入评论链路） |
| **3. 人工审核** | `video_comments.status`（draft / assigned / done）+ CommentComposer 编辑器 + AI 建议可改后保存 | 无「待审核 → 通过」状态机，无批量审核视图 |
| **4. 腾讯文档同步** | 兼职格式 CSV 导出已存在（`routes/mining.py:192-278`），目前流程是导出后手动发给兼职 | 腾讯文档 API 对接完全是新面；最佳架构模板是 TikHub 集成（`csm_core/monitor/tikhub/client.py`：keyring 存密钥、config 驱动、错误映射、额度熔断） |

---

## 1. 总体流程

```
关键词 + 按平台分组的筛选条件（时间/类型/排序，UI 只显示该平台真实支持的档位）
        │
        ▼
三平台并发搜索（能下推的参数下推，快手时间条件本地后过滤+自动补页）
        │
        ▼
全局去重 + 已评论反查（现有，不动）
        │
        ▼
品牌评论预过滤：抓每视频前 20 条评论 → 命中品牌词 1 条即排除
        │  抖音走 TikHub API（本地签名是桩），B站/快手走本地免费路径
        │  抓到的评论文本【持久化】到 videos.top_comments_json（供生成环节复用，省一次抓取/计费）
        ▼
候选池（MiningView 视频列表，现有）
        │  勾选 N 个视频 → 选模板策略 → 批量生成
        ▼
AI 生成（A 档上下文）：模板 × (元数据 + 前20条热评 + AI速览) → 个性化改写
        │  → ai_flavor 确定性检查 → 超标自动重写一次
        │  产出：每视频一套楼层（tier 1 主评 / tier≥2 盖楼），review_status = pending
        ▼
人工审核（新「待审核」tab）：直接改文案 → 通过（改完即背书）；不满意可单视频重新生成覆盖
        │
        ▼
同步腾讯文档：审核通过的批次 append 到你现有的固定共享表格（输入表格链接即可）
        │  评论带图的行只写「有图 N 张，图另发」标记 —— 图由你手机直接发给兼职
        ▼
兼职按表执行评论，回填「执行状态 / 评论链接」
        │
        ▼（Phase 3 可选闭环）
定时回读表格 → 标 done → 自动 sync_to_monitor 建评论留存监测任务（复用现有 sync_to_monitor.py）
```

---

## 2. 环节一：视频筛选

### 2.1 平台筛选能力矩阵（UI 按平台分组展示，只给真实存在的选项）

| 维度 | 抖音（浏览器截包） | B站（WBI 签名直连） | 快手（页内 GraphQL） |
|---|---|---|---|
| 时间范围 | `publish_time` 档位：**不限 / 一天内 / 一周内 / 半年内**（只有档位，无任意区间）；URL 参数追加即可 | `pubtime_begin_s` / `pubtime_end_s`：**任意日期区间**（日期选择器）；加进 `raw_params` 即可，签名器对参数不敏感（`bilibili_search.py:165-170`） | 无服务端参数 → UI 给日期区间但标注「本地过滤」，按 `published_at` 后过滤 + 自动多翻页补偿产出 |
| 排序 | `sort_type`：综合 / 最多点赞 / 最新发布 | `order`：综合 / 最多点击 / 最新发布 / 最多弹幕 / 最多收藏 | 无（默认综合，UI 不显示） |
| 内容类型 | **视频 / 图文** 多选：视频走现有 `type=video`；图文走综合搜索 + 按 `aweme_type`/images 字段后过滤（`raw_json` 已存全量原始数据） | 仅视频（专栏不做，已拍板） | 仅视频 |
| 时长过滤 | `filter_duration` 档位 | `duration` 档位 | 本地后过滤（`duration_sec` 已入库） |

### 2.2 数据结构

`mining_jobs.filters_json`（新列，schema v13）按平台分组，与 UI 一一对应：

```json
{
  "douyin":   {"publish_time": "7", "sort": "default", "content_types": ["video", "note"]},
  "bilibili": {"order": "totalrank", "time_begin": "2026-08-01", "time_end": "2026-08-31"},
  "kuaishou": {"time_begin": "2026-08-01", "time_end": "2026-08-31"}
}
```

- `SearchAdapter.search()` 签名加 `filters: dict` 参数，三个适配器各取自己那份；快手的时间条件由 runner 在 `_on_card` 后过滤（不满足的卡不入库、不计数，adapter 自然继续翻页直到 `target_count` 或页数上限）。
- 迁移注意 `_migrate` 会重复执行所有迁移函数的坑——只用幂等的 CREATE/`PRAGMA table_info` 判存 ALTER，同 v8 写法。
- StartJobModal 改为「平台勾选 → 每个已勾选平台展开自己的筛选块」。

### 2.3 品牌评论预过滤（已拍板参数）

| 参数 | 现值 | 定稿值 | 去向 |
|---|---|---|---|
| 抓取条数 | 30 | **20** | `AppConfig.mining_prefilter_top_n = 20` |
| 排除阈值 | ≥3 条命中 | **≥1 条** | `AppConfig.mining_prefilter_threshold = 1` |
| 品牌词来源 | 每任务手填 | 全局默认（复用 `AppConfig.brand_memory.own_brands`）+ 每任务可覆盖 | 任务弹窗预填全局值 |

- 判定口径：任意评论文本命中品牌词（子串匹配、去空白、大小写不敏感，现有 `count_brand_hits` 逻辑不变）。
- 「前 20 条」= 平台评论接口默认热门序（B站 `mode=3`、抖音/快手接口默认），与访客打开评论区看到的顺序一致。
- 评论文本 + 点赞数持久化到 `videos.top_comments_json`：① 生成环节当评论区语料；② 被排除的视频在 UI 可见「命中了哪条评论」。

### 2.4 评论抓取路由（已拍板：开 TikHub）

- **抖音 → TikHub API**（`/api/v1/douyin/app/v3/fetch_video_comments`，已集成的 `CommentApiAdapter`）。本地 X-Bogus 是假桩（`douyin_comment.py:258-268`），不可用。
- **B站 / 快手 → 本地免费路径**（现有适配器工作正常），省 2/3 的 TikHub 额度；本地连续失败可在设置里手动切到 TikHub。
- 计费参考：每任务约 50 条抖音视频 × 1 次调用（20 条评论一页拿满）。
- 实现：`comment_prefilter.fetch_video_comment_texts` 增加路由层——抖音固定取 TikHub adapter（`build_api_adapters` 产物），其余取本地 adapter；沿用 `task.id=None` 旁路共享缓存的隔离语义。

---

## 3. 环节二：智能评论生成

### 3.1 生成输入（已拍板：A 档）

标题 / 作者 / 时长 / 播放点赞 + **前 20 条热评文本**（预过滤已抓，零额外成本）+ AI 速览缓存。封面图 vision、ASR 均不做（后续想加再说）。

### 3.2 改写流程

```
选模板（人工从模板库挑 / 或按 tags×平台自动轮换，避免同一模板高频出现）
   │
   ▼
LLM 改写   system = 改写规则 + 去AI味负面清单（可拼接用户的 role=humanize Skill 正文）
           user   = 视频信息块 + 评论区样本块 + 模板原文 + 形式要求（主评/盖楼第N层+前层内容/附图说明）
   │
   ▼
确定性检查  ai_flavor_parts(text)（scoring/ai_flavor.py，零 LLM）：AI 连接词/排比/总结腔/句长单调
   │  超阈值 → 带着违规项自动重写一次；仍超标 → 保留但在审核视图标黄
   ▼
落库 video_comments（source='ai_suggested', review_status='pending', template_id, ai_flavor_score）
```

**改写规则（prompt 要点，做成可编辑配置 `mining_rewrite_prompt`，沿用 `---user---` 分隔符惯例）**：

1. 保留模板的核心卖点与品牌词，其余全部重写，禁止逐句同义替换；
2. 必须引用视频具体元素 ≥1 处（标题里的场景/评论区热议的点），让评论「像看过这条视频的人写的」；
3. 模仿评论区样本的语言风格（口语度、emoji 密度、句子长短）；
4. 长度 = 模板 ±30%；
5. 负面清单：首先/其次/综上/不是…而是…/值得一提的是 等 AI 连接词（复用 `ai_flavor.py` 词表 + `scoring.extra_ai_words`）；
6. 不得虚构具体使用时长、价格、售后经历等可证伪细节（只能改写模板里已有的）；
7. 盖楼层（tier≥2）：必须与前层形成对话感（补充/追问/附和），不能是独立评论换个位置。

### 3.3 形式支持（已拍板：附图=人工手机发图）

- **盖楼跟评**：已有 `tier` 建模。批量生成时可配「每视频生成 N 层」，第 2 层起把已生成的前层文本注入 prompt（现有 `previous_tiers` 机制照搬）。
- **评论附图**：`image_ids_json` 已支持在 app 里给评论挂图（审核时能看到）。图**不进腾讯文档**——同步时该行只写「有图 N 张，图另发」，图由你用手机直接发给兼职。app 内挂图仅作为「这条评论要配哪张图」的记录。

### 3.4 批量生成服务

- 新服务 `comment_generation_service`（仿 `mining_ai_service` 模式），新端点 `POST /api/mining/generate_batch {video_ids[], tiers_per_video, template_strategy, tone_hint}`；`tiers_per_video` 上限 **3**（与腾讯文档表格的三层结构对齐）。
- 逐视频串行调 LLM（避免并发打爆额度），进度走现有 `event_bus` SSE（`generation.progress` / `generation.finished`）。
- 失败单视频跳过并记入结果，不阻塞整批。

---

## 4. 环节三：人工审核（已拍板：直接改文案，无驳回循环）

### 4.1 状态机（新列，不动现有 `status`）

现有 `status`（draft/assigned/done）挂着「→done 自动入模板库」的 DAO 钩子，不宜重载。新增独立列：

```
video_comments 加列:
  review_status   TEXT NOT NULL DEFAULT ''   -- '' | pending | approved | synced | executed
  template_id     INTEGER NULL REFERENCES comment_templates(id)
  ai_flavor_score REAL NULL
  reviewed_at     TEXT NULL
  synced_at       TEXT NULL
```

```
AI生成 → pending ──(改文案后)通过──→ approved ──同步──→ synced ──兼职执行(回读/手动)──→ executed
              └─ 不满意 → 「重新生成」按钮覆盖草稿（仍是 pending），无 rejected 状态
人工手写的评论（source='manual'）默认 review_status='approved'，不进审核队列。
```

`executed` 时把现有 `status` 推到 `done`——沿用「发出的评论自动入模板库」钩子，改写得好的评论自然沉淀回模板库，形成语料飞轮。

### 4.2 审核 UI

- MiningView 顶部 tab 加「待审核」（现有 unread/done/all 旁），列出含 `pending` 评论的视频。
- 右侧详情面板复用现有 FloorList + CommentComposer（编辑能力全有），叠加：AI 味评分徽标（超标黄标）、命中的模板名、「通过」「重新生成」按钮。
- 中栏底部浮动工具条（现有批量删除的位置）加「批量通过」。
- 端点：`PATCH /api/mining/comments/{id}/review {action: approve}` + `POST /api/mining/comments/review_bulk` + `POST /api/mining/videos/{id}/regenerate`。

---

## 5. 环节四：同步腾讯文档（已拍板：固定表格 + 直填 token，免开放平台注册）

### 5.1 接入方式（已实现：移植官方「龙虾」skill 的 sheet-mcp 调用）

zip 解析结论（2026-09-01，`cdn.addon.tencentsuite.com/static/tencent-docs.zip`）：skill 的表格操作走 **MCP over Streamable HTTP**——

- endpoint：`https://docs.qq.com/api/v6/sheet/mcp`（sheet 精细编辑服务，与 tencent-docs 主服务、slide/doc 服务平级，四服务共用一个 token）
- 鉴权：`Authorization: <TENCENT_DOCS_TOKEN>` 原样直传（无 Bearer 前缀）；token 从 docs.qq.com/scenario/open-claw.html 获取/重置
- 协议：JSON-RPC 2.0（initialize → notifications/initialized → tools/call），响应兼容纯 JSON 与 SSE 帧两种
- 用到的工具：`sheet.get_sheet_info`（子表列表/行列数）、`sheet.get_cell_data`（读表头/链接列，单次 ≤2 万格）、`sheet.set_range_value_by_csv`（CSV 批量追加，≤1MB/次，空字段不覆盖）
- URL 解析：`docs.qq.com/sheet/{file_id}?tab={sheet_id}` —— tab 即子表 id，带 tab 锁定子表，否则取第一张 worksheet
- 错误映射：400006=token 失效、400007=VIP 不足（skill 错误表）
- 已知限制：`sheet.insert_image` 支持插图（base64）但本流程不用（图走手机直发）；token 失效需人工重贴（无 refresh 机制）

### 5.2 模块设计（照搬 TikHub 集成模式）

```
csm_core/sync/tencent_docs/
  client.py      # httpx；openapi 模式=三元组头，cookie 模式=Cookie 头；
                 # HTTP 状态 + body code 双重错误映射，401/过期进程级熔断提示重新粘贴，
                 # 日志脱敏（仿 TikHub _redact）
  sheet.py       # 高层操作：resolve_doc(url→doc_id) / read_header / get_row_count /
                 # append_rows / read_range（回读用）
  errors.py
```

```python
# csm_core/config.py 新增子模型（token 本体走 keyring，provider="tencent_docs"）
class TencentDocsConfig(BaseModel):
    enabled: bool = False
    doc_url: str = ""            # 粘贴表格链接，doc_id 从 URL 解析
    sheet_name: str = ""         # 可选，多 sheet 时指定
    readback_enabled: bool = False
    readback_interval_min: int = 30
    # 列名映射：默认值 = 用户现有表格的实际表头（可在设置页改）
    col_map: dict[str, str] = {
        "seq": "序号", "url": "链接",
        "tier1": "内容一", "img1": "贴图一",
        "tier2": "盖楼内容二", "img2": "贴图二",
        "tier3": "盖楼内容三", "img3": "贴图三",
        "date": "日期",
        "shot1": "截图1", "shot2": "截图2", "shot3": "截图3",   # 兼职回填执行截图
    }
```

### 5.3 对齐现有表格（表头已确认，2026-08-31 截图）

实际表格列：`序号 | 链接 | 内容一 | 贴图一 | 盖楼内容二 | 贴图二 | 盖楼内容三 | 贴图三 | 日期 | 截图1 | 截图2 | 截图3`，按日期分批，批间有橙色分隔行，序号每批从 1 重排。

写入规则：

- **一批 = 一次同步**：追加 N 行，`序号` 从 1 编号，`日期` 写当天（沿用表内 `2026.8.25` 格式）；批间分隔行若 skill API 支持设背景色则写一条橙色空行，不支持则跳过。
- **链接列**：写「视频标题 + 规范链接」（如 `https://www.douyin.com/video/{id}`）。注：现表格里是抖音分享口令格式（`v.douyin.com` 短链+引导语），搜索接口拿不到口令，规范链接手机浏览器/App 均可打开——如兼职流程强依赖口令格式再议。
- **分层列**：tier 1→内容一，tier 2→盖楼内容二，tier 3→盖楼内容三；**盖楼上限 3 层**（与表格结构对齐，批量生成的 `tiers_per_video` 上限=3）。
- **贴图列**：该层评论在 app 里挂了图 → 写「有图，另发」（图走手机直发兼职）。
- **截图1-3**：不写，留给兼职回填执行截图。
- 列定位：读首行表头按 `col_map` 列名匹配定位，不假设列顺序。
- 设置页「测试连接」：读表头 → 显示映射结果绿灯/缺列警告。

### 5.4 同步与幂等

- 触发：审核视图「同步已通过」按钮 → `POST /api/mining/sync_to_docs {video_ids?}`（缺省=全部 approved）。
- 流程：读当前行数 → 组行 → 一次批量 append → 成功后本地记 `sync_batches(id, doc_id, row_start, row_end, video_ids_json, synced_at)` 新表 + 逐条标 `synced`。
- 幂等：靠本地 `review_status='synced'` 门禁（已 synced 不重复入选）；对账/回读按**链接列匹配**（`platform_video_id` 可从规范链接反解，表格无需加隐藏列）。API 失败整批不标 synced，可重试；重试前先读回末尾若干行按链接去重，防「写成功但响应丢失」的双写。
- 降级：`enabled=false` 或调用失败 → 按钮变「导出 CSV」，走现有导出（列结构与表格一致，手动粘贴也快）。

### 5.5 回读闭环（Phase 3，可选但价值大）

现表格无「执行状态」文字列，兼职的完成信号是**截图1-3 贴图**。回读方案取决于 skill API 能否读出「单元格含图片/附件」（zip 解析后确认）：能读 → 定时（`readback_interval_min`）扫「截图1 非空」的行按链接标 `executed`（连带 `status='done'` 触发模板入库），并自动调现有 `sync_to_monitor` 建**评论留存监测任务**；不能读 → 请兼职在截图外加一个「已发」勾选列，或退化为 app 内手动批量标已发。把「发出去」和「活下来」接成闭环。

---

## 6. 数据结构变更汇总（schema v13）

| 对象 | 变更 |
|---|---|
| `mining_jobs` | + `filters_json TEXT DEFAULT '{}'`（按平台分组，见 §2.2） |
| `videos` | + `top_comments_json TEXT NULL`（预过滤抓到的前 20 条评论快照） |
| `video_comments` | + `review_status` / `template_id` / `ai_flavor_score` / `reviewed_at` / `synced_at` |
| 新表 `sync_batches` | 同步对账（见 §5.4） |
| `AppConfig` | + `TencentDocsConfig` 子模型；+ `mining_rewrite_prompt`、`mining_prefilter_top_n=20`、`mining_prefilter_threshold=1` |
| keyring | + provider `tencent_docs`（token；openapi 模式下如有 refresh_token/secret 一并序列化存） |

---

## 7. 分阶段实施（每阶段独立可用）

| 阶段 | 内容 | 备注 |
|---|---|---|
| **P1 搜索筛选 + 预过滤对齐** | 按平台分组的 SearchFilters 贯通三适配器（B站直连参数、抖音 URL 参数+图文、快手后过滤+补页）、预过滤参数化（20/1）+ 抖音走 TikHub 路由 + top_comments_json 持久化、任务弹窗按平台展开筛选块 | ✅ 已实现（2026-09-01，schema v13；sidecar 测试全绿 + vue-tsc 通过） |
| **P2 生成 + 审核** | comment_generation_service + 改写 prompt 配置 + ai_flavor 接入、review_status 状态机 + 「待审核」tab + 批量通过 + 单视频重新生成 | ✅ 已实现（2026-09-01，schema v14；重新生成=对该视频再跑一次批量生成，pending 草稿自动覆盖；sidecar + vitest 全绿） |
| **P3 腾讯文档** | 移植龙虾 skill 的 sheet-mcp 调用为 sidecar client + 表格链接/列名映射设置卡 + 同步/对账 + CSV 降级 | ✅ 已实现（2026-09-01，schema v15；`csm_core/sync/tencent_docs/` + 设置卡 + 引流页「同步腾讯文档」按钮；**回读闭环未做**——等真实 token 验证同步链路后再议）。⚠️ 待真机验证：MCP 握手细节以真实服务为准，设置页「测试连接」即验证入口 |

风险备忘：① 快手时间筛选只能后过滤，产出速率会降；② cookie 模式走私有接口，改版可能失效（CSV 兜底常在）；③ openapi 直填 token 若无 refresh 凭据需每月重贴；④ `_migrate` 重复执行的坑，迁移只写幂等语句。

---

## 8. 决策记录（2026-08-31 拍板）

| # | 决策 |
|---|---|
| 1 | 品牌词命中 **1 条即排除**；判定=任意评论文本命中品牌词 |
| 2 | 时间范围**按平台真实能力分别显示**（抖音档位 / B站任意区间 / 快手本地过滤） |
| 3 | 内容类型：抖音 视频+图文；B站 仅视频（专栏不做）；快手 仅视频 |
| 4 | 抖音评论抓取走 **TikHub API**（key 已有）；B站/快手留本地免费路径 |
| 5 | 视频内容分析 **A 档**（元数据+评论区热评），不做 vision/ASR |
| 6 | 「回复图片」=评论附图；图由用户**手机直发兼职**，不进腾讯文档（表格只标「有图，另发」） |
| 7 | 审核=在 CSM 里**直接改文案后通过**；无驳回状态，不满意就重新生成覆盖 |
| 8 | 腾讯文档：**固定现有表格**（表头：序号/链接/内容一/贴图一/盖楼内容二/贴图二/盖楼内容三/贴图三/日期/截图1-3），粘贴表格链接 + `TENCENT_DOCS_TOKEN` 直连（不注册开放平台）；列映射按表头列名自动对齐 |
| 9 | 「植入」可行：skill 为腾讯官方「龙虾」腾讯文档 Skill（tencent-docs.zip + 单 token 鉴权），sidecar 移植其 HTTP 调用；待办：批准后下载 zip 解析接口定义 |
