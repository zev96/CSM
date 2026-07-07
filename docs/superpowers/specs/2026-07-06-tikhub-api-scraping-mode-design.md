# TikHub 付费 API 抓取模式 —— 设计文档

- 创建:2026-07-06;修订:2026-07-07(并入对抗性审查修正 + 用户两项决策)
- 状态:设计已确认;已过 3 视角对抗性审查;待用户复审本修订版
- 关联:监测模块(知乎问题排名 / 视频评论留存排名)

## 1. 背景与目标

CSM 现在的监测抓取全部走**本地浏览器 / curl_cffi**(依赖登录 cookie、X-Bogus 签名、验证码软着陆),维护脆弱(抖音 X-Bogus 是占位符、cookie 会软封)。用户已开通 **TikHub** 付费聚合 API($0.001/次标准档),希望新增一条**付费 API 抓取通道**,在设置里用**一个全局开关**切换"本地抓取 ⇄ TikHub API",覆盖:

1. **知乎问题**排名监控(品牌名+别名在前 N 条回答**正文**中的命中排名,**默认排序**)。
2. **抖音 / B站 / 快手 评论留存**监控(用户自己的评论是否仍在、排在第几)。

目标:在**不动现有本地适配器、零回归**的前提下,增加可切换的 API 抓取路径,把脆弱平台(尤其抖音评论)的抓取可靠性外包给 TikHub。

## 2. 范围

**纳入:** 全局开关 `data_source_mode`;4 个 API 适配器(`zhihu_question`/`douyin_comment`/`bilibili_comment`/`kuaishou_comment`);视频评论用 TikHub **APP 版**端点。

**排除(即使开 API 也照旧走本地):** 知乎搜索/评论内排名、微信视频号、百度关键词、GEO、mining 模块。

## 3. 关键决策(已与用户拍板)

| # | 决策 | 取值 | 备注 |
|---|---|---|---|
| D1 | 开关粒度 | **全局总开关** | 一个开关切全部 4 类 |
| D2 | API 失败回退 | **报失败 + 通知,不回退** | 成本/行为可预测 |
| D3 | 每视频评论条数 | **每视频一条**自己的评论 | 不改评论数据模型 |
| D4 | 抖音评论扫描深度 | **前 50 条**(count=20 固定 → 最多 3 页) | 见 §6.1 落地方式 |
| D5 | 三家评论翻页 | **自适应**:达目标条数 / API 报尽 / 页失败 三者先到即停 | 见 §7.2 |
| D6 | 视频端点版本 | **APP 版** | 见下方 D6 说明 |
| D7 | 评论监控节奏 | **录入时一次性检查评论留存**,之后不定期 | schedule 默认 manual;成本按录入速率,非每日复算 |

**D6 说明(经审查复核):** 用户现有本地评论抓取走的是各平台 **web 面**;API 若走 **APP 面**,两者热评排序/置顶算法未必逐位一致。**但因 D7——评论是"录入时一次性留存检查",无 per-task 时间序**——不存在"与 web 历史趋势断裂"的问题,故 APP 端点成立。上线前的"顺序核对"因此从 **parity 硬门**降级为 **sanity 核对**(APP 能正确返回目标评论 + rank 合理即可)。

## 4. 已核实的外部事实(实证)

### 4.1 端点与定价(源:下载 TikHub `openapi.json`,1091 端点)
- 用到的端点均走**标准档 $0.001/次**(全 spec 仅 24 个内嵌特殊价,其中 23 个 $0.01;本设计端点均不在其中)。日用量 >1000/天 → $0.0009,降到 30k+/天 $0.0005。
- **无缓存去重**(审查证实):ResponseModel 的 `cache_url` 仅供**请求溯源**,文档明载"won't be returned through the API again",每个 200 都计费。→ 缓存**不能省钱**,但也**不会返回过期数据**(监控每次都是新鲜数据)。

| 平台 | APP 一级评论端点 | 关键参数 | 分页游标 / 结束判据 |
|---|---|---|---|
| 抖音 | `/api/v1/douyin/app/v3/fetch_video_comments` | `aweme_id`、`count`(**固定 20,改则 bug**) | `cursor` + `has_more` |
| B站 | `/api/v1/bilibili/app/fetch_video_comments` | `bv_id`/`av_id`、`mode`(**3=热门**) | `next_offset` + `is_end` |
| 快手 | `/api/v1/kuaishou/app/fetch_video_comment` | `photo_id`、`pcursor` | `pcursor`(`no_more` 结束) |
| 知乎 | `/api/v1/zhihu/web/fetch_question_answers` | `question_id`、`limit`、`cursor`、`session_id`、`order=default` | `paging.is_end` + `paging.next` + `session.id` |

> B站 APP 端点直接收 `bv_id` → 省掉本地那步 BV→aid 二次转换。

### 4.2 知乎返回结构核对(源:用户实测 `response.json`,`question_id=23640683`,`limit=20`)
- **`limit=20` 被真实履行**:一次返回 20 条,无 silent cap。
- 底层是知乎**新版 `/feeds` 流**(`paging.next` = `/questions/{id}/feeds?...order=default`),结构 = `root.data.data[N]`,每项 `type=="question_feed_card"`、`target_type=="answer"`,答案在 `target`(52~53 字段)。
- **正文全文存在**:`target.content` 完整 HTML(实测纯文本 35~5719 字/条)→ 品牌+别名匹配依赖**满足**。
- **顺序 = 默认排序(order=default)**,即访客默认视图序(**用户要的正是这个**);实测 voteup 序非严格递减,证明它是知乎推荐/默认混合序、非纯赞同序,且**与本地老 `/answers?sort_by=default` 未必逐位相同**(见 §13 R1)。
- 本页 20 条均 answer,但 `data.ad_info` 字段存在 → 别的页**可能混非 answer 卡**,normalizer 必须过滤(见 §8.1)。

### 4.3 链接→ID 提取(源:阅读现有 3 个评论适配器)
现有 `_extract_video_id` **全部纯 HTTP/正则、不依赖浏览器**,且已处理短链(抖音 `v.douyin.com` redirect、快手 `/short-video/`+`shareObjectId=`+`v.kuaishou.com`/`/f/`、B站纯正则 BV/AV)→ **API 模式原样复用,零成本**,不需要 TikHub 的链接转换端点。

## 5. 架构设计(方案一:旁路 API 适配器 + 模式感知分派)

### 5.1 原则
"切换抓取方式"只改**怎么拿到那批数据**;拿到后的匹配、结果结构、通知、存储**完全复用**。API 适配器只负责"取数 + 归一化 + 复用匹配"。

### 5.2 新增组件
```
csm_core/monitor/tikhub/
  client.py       # HTTP 客户端:鉴权/BaseURL/自适应翻页(含页失败=异常)/错误映射/
                  #   进程级"余额耗尽"闩/超时/cancel/progress/无自动重试/日志 redact key
  normalize.py    # 各平台原始 JSON → 统一结构(§8)
  zhihu_question_api.py / douyin_comment_api.py / bilibili_comment_api.py / kuaishou_comment_api.py
```

### 5.3 统一接口
每个 API 适配器实现现有 `BaseMonitorAdapter`:`platform: TaskType` + `fetch(task, cancel_token=None, progress_cb=None, **_) -> MonitorResult`(**永不抛异常**,失败返回 `status=failed`)。

### 5.4 分派与注入(经审查修正)
- 注册表 `csm_core/monitor/platforms/__init__.py`:新增 `API_ADAPTERS = {那 4 个 type}`。
- `monitor_loop._run_one()`:
  ```python
  mode = self._data_source_mode      # 见下:需真建注入链
  adapter = (API_ADAPTERS.get(task.type) if mode == "tikhub_api" else None) \
            or self._adapters.get(task.type)
  ```
  → 不在 `API_ADAPTERS` 的 type(baidu/geo)**自动回落本地**。
- **⚠️ 注入链需真建(审查发现 A5/P8):** 现状 `MonitorLoop` 不持有 `data_source_mode`,`monitor_lifecycle.reconfigure()` 只把设置推给各 **adapter**、不写 loop。落地需:`MonitorLoop.__init__` 接收/持有 mode + `reconfigure()` 增加 `loop.set_data_source_mode()`。热重载时 in-flight task 读旧值可接受(下一轮生效)。
- **⚠️ API 模式必须绕过本地反爬限速(审查发现 A2/C2):** `_apply_runtime_settings`(monitor_lifecycle.py:75-83)当前**无条件**给评论平台配 `request_delay 5~15s` + `concurrency=2`;`_run_one` 的 `slot(task.type)` 也模式无关。TikHub QPS 上限 10、自己扛反爬,本地这套会把 API 抓取拖慢 ~100 倍且零意义。落地:`data_source_mode=="tikhub_api"` 时**不给这些平台配本地 pacing**、`_run_one` 对 API 任务**跳过 `slot()`**(或为 API 单独配高并发);API 适配器**不调 `get_pacer()`**。

**本地适配器文件零改动。**

## 6. 配置与设置变更

### 6.1 `csm_core/config.py` → `MonitorConfig` 新增字段
```python
data_source_mode: Literal["local", "tikhub_api"] = "local"   # D1 全局开关
tikhub_base_url: str = "https://api.tikhub.dev"              # 大陆默认;可改 .io
tikhub_video_endpoint: Literal["app", "web"] = "app"         # D6
tikhub_zhihu_limit: int = 20                                 # 知乎每页;实测 20 履行
```

**抖音深度 50 的落地(审查修正 A1/C5a):** `scrape_top_n` 是**现有每任务** config 字段,但 **AddTaskModal 目前根本不写它**(只写 `my_comment_text`+`top_n`),会走兜底 **150**。因此**不能**指望"改个 modal 默认值"。落地二选一(取其一并加测试断言):
- (推荐)**抖音 API 适配器内**把扫描目标定为 `min(task.config.get("scrape_top_n") or 50, 抖音上限50)` —— 不依赖任务里是否写了该字段;
- 或任务创建时**真的**把 `scrape_top_n=50` 写进 `douyin_comment` 任务的 `config`。
- B站/快手 API 适配器扫描目标 = `min(task.config.get("scrape_top_n") or 150, 平台上限)`,**每平台设硬上限**(见 §11),不放任 150 无界翻页。

### 6.2 API Key
- **不写入 settings.json**;走现有 keyring 路由 `/api/keyring/{provider}`,`provider="tikhub"`。
- keyring 在打包版可用性:已由审查**真机验证**(release 同款 spec 打 onefile exe 跑 keyring 往返 = OK)。加固见 §13 R6。

### 6.3 前端 UI 规格(`SettingsView.vue` 监测 section)

**位置:** 「监测」section **最顶部**(现有 Cookie 池之前)。理由:数据源决定下面一切——API 模式下根本不需要 Cookie 池 / 浏览器引擎。用现有 section 子标题范式(`mb-3 mt-5 font-display text-[13px] font-semibold`,color `var(--ink)`)起一块 **「抓取数据源」**。

**控件(全部复用现有组件,不自造):**
1. **主开关行** —— `<SettingsRow label="付费 API 抓取(TikHub)" hint="开=知乎问题+抖音/B站/快手评论走 TikHub 付费 API;关=本地浏览器抓取">` + `<FormToggle>`(现成 38×22 pill,开为 `var(--primary)`)。
   - 绑定:`:model-value="get('monitor.data_source_mode')==='tikhub_api'"`;`@update:model-value="v => setField('monitor.data_source_mode', v?'tikhub_api':'local')"`(布尔 ↔ Literal 映射)。autosave PATCH → 热重载 + §5.4 mode 注入。
2. **开关 ON 时条件展开**(`v-if data_source_mode==='tikhub_api'`)三行:
   - **API Key** —— 复用「知乎 Access Secret」整套:`<input type=password 260×34 rounded-10 font-mono>` + 「已配置/未配置」状态 span(绿/灰)+ `<Btn variant=solid small>保存</Btn>`;保存走 `keyringSet("tikhub", raw)`(**不进 draft**),状态查 `keyringStatus("tikhub")`。placeholder「粘贴 TikHub API Key」/ 已存时「已保存 — 点击输入新值可覆盖」。
   - **接口区域(Base URL)** —— `<FormSelect width=200>`,options `[{label:'大陆(api.tikhub.dev)',value:'https://api.tikhub.dev'},{label:'海外(api.tikhub.io)',value:'https://api.tikhub.io'}]`,绑 `monitor.tikhub_base_url`,默认大陆。归「高级」小字,大多数人不动。
   - **成本提示行** —— 一行 `text-[11.5px] text-ink-3`:「按次计费 $0.001/次。评论=录入时一次性;知乎=按你设的频率。改成高频复算会显著增加费用。」
3. **本地专属行灰化(打磨,可选)** —— `data_source_mode==='tikhub_api'` 时,下方「浏览器引擎 / 多账号轮换 / 每账号任务数 / Cookie 冷却」这些**本地反爬**行加 `opacity-50` + hint 追加「(仅本地模式生效)」。Cookie 池 + 知乎 Access Secret **保留常亮**(知乎搜索排名仍走官方 Secret;Cookie 池对其它本地任务仍有用)。

**交互一致性:** 全页无独立保存按钮(autosave);唯 Key 保存是独立按钮(与知乎 Secret 一致,因写 keyring 不走 draft)。开关切换即时 PATCH `monitor.data_source_mode` → 后端深合并 + `reconfigure()` 注入新 mode。

## 7. 数据流

### 7.1 知乎问题(审查修正 B1/P7:按 top_n 自适应翻页)
```
task(问题URL, config={target_brand, aliases, top_n})
  → 提取 question_id
  → 目标条数 = min(40, top_n)                      # 本地 clamp 上限即 40
  → client.paginate(zhihu_answers(qid, limit=20, cursor/session), target=目标条数)
       # top_n≤20 → 1 次;top_n∈(21,40] → 2 次(成本 ×2)
  → normalize.zhihu(): 过滤 answer 卡、拆 target、连续编号
  → 复用现有"品牌名+别名 命中正文(order=default 序)"匹配 → 命中最靠前位 = rank
  → MonitorResult(rank, metric{answers, order:"default", source:"tikhub", scanned_full:bool})
```

### 7.2 视频评论(自适应翻页 + 页失败=整体失败,审查修正 A3/C4/C6)
```
task(视频URL, config={my_comment_text, top_n, scrape_top_n?})
  → _extract_video_id(session, url)                 # 复用现有,含短链
  → 目标 = 抖音 min(scrape_top_n or 50, 50) / B站快手 min(scrape_top_n or 150, 平台上限)
  → client.paginate(page_fn, target, max_pages=硬上限):
        正常停:达 target / has_more=false / is_end / pcursor=no_more / 空页
        异常停:任一页 HTTP/结构失败 → **抛异常**(绝不返回残缺列表)
                达 max_pages 硬上限(如 10)仍未终止 → 当异常(防跑飞计费)
  → normalize.<platform>() → [{text, author, likes}]（含 §8.2 的置顶/去重规则)
  → 复用 _comment_common.build_match_result(my_comment_text, comments)
  → MonitorResult(rank, metric{hot_comments, matched, scanned_full:True, source:"tikhub"})
  # 任一页失败 → 整体 status=failed(附已抓页数),绝不拿残缺列表匹配 → 不会把"埋得深/抓失败"误报成"评论被删"
```

## 8. Normalizer 规格

### 8.1 知乎(已由 response.json 钉死)
- 入口 `root.data.data`;**过滤条件三者同时成立**:`item.type=="question_feed_card" and item.target_type=="answer" and item.get("target")`。跳过的非 answer 卡**计数记录**,rank 取**过滤后连续 index+1**(本地无广告卡概念,口径对齐)。
- 每条取 `item.target`:`content`(HTML)、`author.name`、`voteup_count`、`comment_count`、`created_time`、`id`、`url`。
- **正文清洗用与本地 fast-path 完全相同的 `_strip_tags`**(zhihu_question.py:319),不另写;文档承认与 browser 兜底路径本就有细微差异(非本设计引入),不宣称逐字节一致(审查 P5)。
- 排名 = 默认排序(order=default)下过滤后位置(用户要的访客视图序,§3 D6)。
- 分页:`paging.is_end` / `paging.next`(cursor)/ `session.id`。

### 8.2 评论(统一 `{text,author,likes}` 喂 `build_match_result`;字段路径待 §12 sanity 核对)
- **抖音 APP**:`comments[].text` / `.user.nickname` / `.digg_count`;游标 `cursor`,续抓判据 `has_more`。
- **B站 APP `mode=3`**:`replies[].content.message` / `.member.uname` / `.like`;**首屏必须复刻本地规则:置顶(upper.top)→ rank1,再热评,并按文本去重**(bilibili_comment.py:197-232);游标 `next_offset`,结束 `is_end`。
- **快手 APP**:评论文本/作者/点赞(对应本地 `content`/`authorName`/`likedCount`);游标 `pcursor`,`no_more` 结束;`photo_id` 用本地抽出的 photoId(短串 eID),§12 核对不 0 命中。

## 9. 错误处理(D2 无回退,经审查加固)
- TikHub `code!=200`/HTTP 非 2xx → 中文原因 + `status`:`402`→"TikHub 余额不足"、`429`→"限流"(可 `risk_control`)、`401/403`→"鉴权失败/Key 无效"、其它→"API 错误(code=…)"。**绝不启动本地浏览器。**
- **进程级"余额耗尽"闩(A4/C3):** client 见到**任一** `402` 立即置进程级闩(跨平台,因余额是账户级);`_run_one` 在 API 模式下**先查闩**,置位则本轮剩余任务**直接跳过、不发请求、聚合成一条通知**(而非每任务刷一条)。闩在下一整点或用户手动重置。
- **不自动重试(C5c):** client 网络错误/超时直接 `failed`,**不重试**(每次重试 = 新计费,无幂等)。
- **分页页失败/结构异常 → 整体 failed**(§7.2),附 raw first500 日志,但**redact 掉 Authorization 头/key**(R7)。
- 失败经现有三通道通知(系统通知 + sticky toast + 任务栏闪)。

## 10. 测试策略
- **Fixture 回归**:`response.json` 存为 `sidecar/tests/fixtures/tikhub_zhihu_answers.json`;断言 normalize.zhihu 拆信封、过滤非 answer 卡、连续编号、content 非空、用 `_strip_tags`。
- **client 单测**:自适应翻页(达标/报尽/空页停);**页失败 → 抛异常不返残缺**;`max_pages` 硬闸;`cancel_token` 中断;错误映射(402/429/401/超时);**402 置闩 + 本轮短路 + 单条通知**;**不重试**。
- **成本护栏测**:断言抖音 API 适配器扫描 ≤50(=最多 3 页),不因 config 缺 scrape_top_n 而跑 150。
- **评论 normalizer 测**:各平台样本(§12 实测后落 fixture)映射 `{text,author,likes}`;B站置顶→rank1 + 去重。
- **dispatch 测**:`tikhub_api` 时 4 类路由 API 适配器、baidu 回落本地;**API 模式跳过 pacing/slot**。
- **打包 smoke test**:build_sidecar 后跑一次 keyring round-trip,失败即 fail 构建(R6)。
- ⚠️ sidecar 测试**不进默认 CI**,必须显式 `pytest sidecar/tests/`。

## 11. 成本模型(经审查重写)
**通式(无缓存去重):成本 = Σ 各任务(每次运行页数 × 运行次数) × 单价。** "运行次数"是最大乘数。
- **评论(D7:录入时一次性):** 成本按**新增任务速率**,非每日复算。抖音 50 条 = ≤3 页/次;若一天录入 200 条视频 = ≤600 次 = **≤$0.6 当天**,之后不复算。B站/快手同理按录入量、按各自深度上限。
- **知乎:** 若每题每天 1 次、top_n≤20 = 1 页 → 200 题 ≈ $0.2/天 ≈ **$6/月**;top_n∈(21,40] 成本 ×2。知乎若设为**每日复算**才有月度累积(评论没有)。
- **每平台深度上限**(防 B站/快手 150 无界):建议抖音 50、B站/快手各设一个上限(如 100),写进适配器,别放任默认 150 × 8 页。
- **结论区间:** 以用户当前用法(评论一次性 + 知乎每日),月成本约 **$6–24 量级**;真正会让成本上台阶的只有"把评论/知乎设成高频复算",UI 成本提示需明示这一点。

## 12. 开工前实测清单(sanity 核对,非 parity 硬门;各 $0.001)
用用户 token 各打 1 发,落 fixture:
1. **抖音** `douyin/app/v3/fetch_video_comments`:字段路径 `text`/`user.nickname`/`digg_count` + `has_more`/`cursor`;确认能定位到一条已知评论(留存可判)。
2. **快手** `kuaishou/app/fetch_video_comment`:字段 + `pcursor` 结束判据 + 本地 photoId(eID)直接可用不 0 命中。
3. **B站** `bilibili/app/fetch_video_comments?mode=3`:字段 + `is_end`/`next_offset` + **是否含置顶、排在何处**(找一个有 UP 置顶评论的视频)。
> 知乎侧已由 `response.json` 确认。核对目标是"能正确返回目标评论 + rank 合理"(留存判定可靠),非"与本地逐位相同"。

## 13. 风险与未决(经审查更新)
- **R1 知乎一次性基线断点(低,U 已接受):** 本地 `/answers` 序 vs API `/feeds?order=default` 序未必逐位相同;切换那一刻同一题历史 rank 可能小跳。这是**换数据源的一次性现象**,metric 标 `source` 即可。用户要的就是默认排序访客视图,持续语义无问题。
- **R2 评论 APP vs web 顺序(低,因 D7 降级):** 无 per-task 时间序,不构成趋势断裂;仅需 §12 sanity 核对。
- **R3 `rank=-1` 语义二义(中,留存用途关键):** "没找到"可能是"真被删"或"埋在扫描深度外"。metric 增 `scanned_full`/`scope_total`,让"埋得深"不被误读成"被删";§7.2 保证页失败=failed(不产生假"没找到")。必要时对留存任务放深扫描深度。
- **R4 TikHub 单点故障(中):** 宕机 = 4 平台同时黑(D2 不回退)。缓解:全局开关本就能**一键切回本地**(强调该出口);client 对连续端点级 5xx 聚合成一条"TikHub 疑似不可用"通知,别刷屏。
- **R5 成本失控(中,已加护栏):** 靠 §6.1 每平台深度上限 + §7.2 max_pages 硬闸 + §11 频率提示 + §9 余额闩共同兜底。
- **R6 keyring 隐性依赖(中,非阻断):** 机制已实测可用,但依赖 PyInstaller 自带 hook 隐性兜底、失效时静默无告警。加固:spec 显式 `copy_metadata('keyring')` + hiddenimports(`win32ctypes.core`/`keyring.backends.Windows`);`pyproject.toml` 钉 `pywin32-ctypes>=0.2.0; sys_platform=='win32'`;§10 打包 smoke test;让用户在打包版真配一次 key 跑一次采集补真机验证。
- **R7 日志泄 key(中):** client 打 raw 响应时必须 **redact `Authorization` 头**;key 不落 settings.json、不进前端。
- **R8 APP 端点 ID 口径:** 抖音 `aweme_id`、快手 `photo_id`(eID)、B站 `bv_id` 与现有 `_extract_video_id` 输出对齐,§12 核对。

## 14. 对抗性审查修正记录(3 视角,可追溯)
| 编号 | 视角 | 发现 | 处置 |
|---|---|---|---|
| A1/C5a | 成本 | 抖音"50=3页"依赖不存在的 modal 默认值,实跑 150→8 页(×2.7) | §6.1 改为适配器内定 50 + §10 护栏测 |
| C1 | 成本 | 缓存不去重、每次计费;频率是最大乘数 | §4.1 + §11 按频率重写;D7 澄清评论一次性 |
| A2/C2 | 成本/效率 | 本地 5-15s pacing+并发2 误带进 API,慢~100× | §5.4 API 模式绕过 pacer/slot |
| A3/C4 | 正确性 | 分页页失败拿残缺列表 → 误报 rank=-1(留存误判) | §7.2/§9 页失败=整体 failed;§13 R3 |
| A4/C3 | 失败 | 402 无跨平台短路 → 通知洪水 + 烧调用 | §9 进程级余额闩 + 聚合通知 |
| C5c | 成本 | 自动重试会重复计费 | §9 明确不重试 |
| C6 | 成本 | 无 max_pages 硬闸、B站/快手 150 无界 | §7.2 max_pages + §6.1/§11 深度上限 |
| P1 | 口径 | `/feeds` vs `/answers` 顺序不同 | §13 R1(U 要默认序,降级为一次性断点) |
| P2/P3/P4 | 口径 | 评论 APP vs 本地 web 顺序、B站置顶/去重、快手 photoId | §8.2 复刻置顶+去重;§12 sanity;因 D7 降级 |
| P5 | 口径 | 三套正文清洗不逐字节一致 | §8.1 统一 `_strip_tags`,不宣称等价 |
| P6 | 口径 | 广告卡过滤依据不准 | §8.1 三条件过滤 + 连续编号 |
| P7/C5b | 正确性/成本 | 知乎 top_n>20 单页漏命中 + 文档自相矛盾 | §7.1 自适应翻页 + §11 成本注 |
| P8/A5 | 架构 | 分派注入链非现成 | §5.4 明确需真建注入链 |
| K1-3 | 安全 | keyring 可用但隐性依赖/静默失效/未真机验证 | §13 R6 加固 |
| — | 安全 | 日志可能泄 key | §13 R7 / §9 redact |
| — | 可用性 | TikHub 单点 | §13 R4 一键切回本地 |

**放行(设计做对):** count=20 锁死、limit=20 履行、B站省 aid、链接→ID 复用本地正则、key 只存 keyring、方案一旁路架构本身。
