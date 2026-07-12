# GEO 采集升级设计(Plan A+B v2)

- 日期:2026-07-09
- 分支:`claude/geo-collection-upgrade-ccd4f9`
- 状态:已通过用户评审 + 3 路对抗性审查,待拆实施计划
- 范围:GEO 监控采集管线的**效率(更快)+ 稳定(不再频繁采集失败)+ 准确(数据可信)+ 可诊断(看得懂失败)**四项;**不含**去 RPA 化迁移(列为后续研究专项 C)

---

## 1. 背景与根因

GEO 监控对 5 个 AI 平台就一批关键词提问,判定品牌是否被提及、排名、情感、信源。5 个平台分两类采集方式:

| 类别 | 平台 | 方式 | 特性 |
|---|---|---|---|
| API | 豆包(Ark bot `/bots/chat/completions`)、通义(DashScope `qwen-plus` + `enable_search`) | httpx 直连 | 快、稳、信源带真实 URL |
| RPA | Kimi、DeepSeek、腾讯元宝 | patchright 驱动有头(屏外)Chrome + 持久登录档 | 慢、脆、登录会过期、选择器会漂 |

**一个架构事实同时造成两个症状**:三个平台靠驱动真实浏览器采集,RPA 天然又慢又脆。

### 现状关键代码事实(已核实)

- 全串行:`for kw in keywords: for plat in platforms` 逐格跑(`csm_core/monitor/platforms/geo_query.py:88`);每格 `provider.query()` + 一次 `extract()` LLM 结构化。
- RPA 每格重开一次 Chrome(`rpa/_session.py:27` → `launched_page`),冷启 + goto + 登录检查全重来 → 最大墙钟浪费。
- GEO 任务级并发被钉死为 1(`geo_query.py:181` `configure_concurrency("geo_query",1)`),防两任务抢同一 profile。**此约束保留**。
- API provider 每次新建 httpx、无连接复用。
- GEO 路径**未接**熔断(`CircuitBreaker` 存在于 `browser_infra/rate_limit.py:155` 但 GEO 未用)、**未接**任何 pacing、无重试。
- 失败状态枚举 `AnswerStatus = ok/empty/blocked/error`(`geo/models.py:13`);运行状态 `MonitorStatus = ok/failed/risk_control/skipped/error`(`monitor/base.py:68`,Pydantic Literal)。
- 卡片副标题「采集失败 / 够不到平台」是前端写死兜底(`GeoPlatformStrip.vue:68`),对 `error|blocked` 一律显示;真实原因存在 `geo_cells.raw_json.error`,但前端从不读 `raw_json`。
- KPI 分母只算 `status=="ok"` 的 cell(`geo/metrics.py:32-37`),失败平台被静默移出 SoC/首推率分母。
- 现状实测口径:一轮 27 关键词×5 平台 ≈ **2–5 小时**(81 个 RPA cell,每个 70–230s;加 54 个 API cell)。

### 失败诊断(问题 2 的答案,已由真实 DB/日志证实)

从用户 `monitor.db` 的 `geo_cells.raw_json.error` 与 `sidecar.log` 读到的真实报错:

- **DeepSeek**:`DeepSeek 未登录`(blocked,日志里登录态 True↔False 抖动) / `Page.click Timeout 30000ms 找不到发送按钮`(选择器漂)。
- **Kimi**:已登录但 `wait_stream_done exceeded 120s`(流不结束) / `Page.click Timeout` / `Target page/context/browser closed`。
- **通义**:keyring 中 `qwen` key 在,历史零失败;偶发失败大概率是 DashScope 临时错误/限流/欠费或内容风控。

「有时候(间歇)」= RPA 登录会过期 + 选择器/流检测对站点慢/改版脆。API 平台稳得多。

---

## 2. 目标与非目标

**目标**
1. 一轮墙钟从 2–5 小时降到 ~1–1.25 小时(含防风控节奏)。
2. 大幅减少「采集失败」:登录/选择器/超时问题 fail-fast、短路、有限重试。
3. 卡片显示真实失败原因,用户可自助判断(去登录 / 重试 / 查配额)。
4. 数据更可信:失败平台不再静默改变分母;抑制单次采样抖动。

**非目标(明确排除)**
- 去 RPA 化(把 Kimi/DeepSeek/元宝 迁到官方联网 API 或第三方 GEO 数据源)——列为后续研究专项 C,需先验证信源可行性(Kimi API `annotations` 恒 0 是当初改 RPA 的原因)。
- 不改运行状态枚举、不改 KPI 分母口径的既有语义(只做增量附加)。

---

## 3. 核心架构:任务内双车道并发

**任务级并发仍为 1**(不动 `configure_concurrency("geo_query",1)`);并发只发生在**单个任务内部**。

```
一个 GEO 任务(fetch 主线程持有 slot("geo_query"),cap=1)
├─ API 车道  (豆包 / 通义)
│    线程池并发所有 (关键词 × 平台 × 样本) 调用,复用 per-provider httpx.Client
│    池上限 4–5(约 16–30 RPM,个人档限流之下);429/连接失败可带 Retry-After 单次重试
├─ RPA 车道  (Kimi / DeepSeek / 元宝)
│    每平台 1 个浏览器,开一次 → 循环全部关键词(每关键词 goto 首页重置会话)→ 关一次
│    3 平台之间并发(各自独立 profile 档,互不冲突);平台内关键词串行 + 答后 jitter
├─ extract 池 (LLM 结构化)
│    答案到手即并发结构化(有界池),不阻塞采集;复用单个 extract client
└─ 汇聚:所有 lane join 完成后,单一 checked_at 时间戳,单次 record_run 落库
墙钟 ≈ max(API 车道, 最慢 RPA 平台跑完自己 27 关键词)
```

**并发安全性(审查已验证,可坚持)**:`mining_browser.launched_page` 每次调用各自 `sync_playwright().start()`,无模块级单例/threading.local;三平台用独立 profile 目录(`geo_kimi`/`geo_deepseek`/`geo_yuanbao`);patchright 走 stdio pipe 不占 CDP 端口。`httpx.Client`、extract client 跨线程共享均线程安全。SQLite 走 thread-local 连接,worker 线程不碰库,仅主线程末尾单事务写入。

---

## 4. 组件设计

### 4.1 双车道调度器(替换现串行循环)

- 按 provider 的 `.mode`(api/rpa)分车道。
- API 车道:`ThreadPoolExecutor(max_workers=api_pool_size)` 提交所有 (kw × api平台 × sample) 任务。
- RPA 车道:每平台一个 worker 线程,内部持一个复用浏览器,串行遍历关键词。三 worker 并发。
- extract:独立有界池;或在各 cell 完成回调里提交。
- **进度**:单一原子计数器(`threading.Lock` 或 `itertools.count` + 锁),完成一格 +1,统一调用 `progress_cb(done, total)`。禁止各 lane 各报自己的下标(否则进度倒跳,且 `test_geo_query_adapter.py:62` 钉了 `progress[-1]==(4,4)` 单调性)。
- **取消**:fetch 主线程必须 `join` 所有 worker 后才返回;不能在第一个 `_CancelledFetch` 就 return(否则其余 2 个 headed Chrome 变孤儿,`launched_page` 的 `finally` kill 不到)。RPA 的 `page.goto`/`submit_query`/`start_new_chat` 阶段补 cancel 检查点,缩短 Stop 响应延迟。
- **resume_from**:从「线性下标之前皆完成」改为「已完成的 (平台,关键词) 集合」;并发下不能用下标。

### 4.2 RPA 浏览器复用 + 会话重置 + 防风控节奏

- **会话重置(致命修复①)**:DeepSeek/Kimi 的 `new_chat_sel=None` 注释假设「打开即新会话」只在每格重启模型下成立。复用浏览器后**每个关键词用 `page.goto(spec.url)` 回首页重置会话**(三站通用、最便宜),避免 27 关键词灌进同一对话污染提及/排名 + 暴露机器人签名。元宝保留其现有新建按钮亦可,但统一走 goto 更简单。
- **节奏(修复:RequestPacer 是 no-op)**:`RequestPacer.wait()` 是「目标间隔−已耗时」,RPA 每题耗 60–180s ≫ 15s 上限 → sleep 恒 0。改为**答案完成后显式 `time.sleep(U(jitter_min, jitter_max))`**「思考时间」,默认 **15–45s**。
- **顺序洗牌**:每轮对关键词顺序随机洗牌(避免固定顺序指纹)。
- **启动抖动**:定时任务在预定 `HH:MM` 基础上加随机 0–20min 启动延迟(scheduler 现为固定时刻,固定时刻+固定顺序+零阅读=周期性指纹)。
- **睡眠/补跑守卫**:`time.monotonic()` 在 Windows 含睡眠时间,睡 30min 醒来会瞬间抛超时。定时任务加 run-window 守卫:迟到超过 N 小时改跳过/降级提示,避免用户开机瞬间 3 个 Chrome 全速开跑。

### 4.3 RPA 韧性(治采集失败)

- **登录 gate 改 advisory(致命修复③)**:预探针(`_session.py:53` goto+固定 1.5s 单帧判定)是代码库自己证伪过的旧模式(`_flow.py:109` 注释:元宝已登录却误报),且与长驻浏览器抢同一 profile 锁。**不用它做权威 gate**。改为:
  - 探针结果仅作 advisory 在设置页展示。
  - 运行时 gate = 「**首关键词返回 blocked → 跳过该平台余下关键词**」(复用架构下 fail-fast 免费,采集路径用的是 10s 轮询的 `wait_login_ready`,可信)。
  - GEO 运行期间,登录窗口打开动作提示「采集进行中,稍后再试」,避免撞锁制造假未登录。
- **连败短路(替换 CircuitBreaker)**:`CircuitBreaker.record_success` 清空失败窗(`rate_limit.py:171`),时好时坏的平台永不熔断;连败熔断也要先烧 5×360s。改为**轻量规则:同平台连续 3 个关键词失败 → 本平台余量跳过**(发合成 cell,原因=平台异常已短路)。
- **选择器兜底**:发送按钮加多组候选选择器 + 键盘 Enter 兜底。
- **超时先验尸再重试**:`wait_stream_done` deadline 判定在 done 判定之前(`_flow.py:288`),慢站/睡眠唤醒下答案可能已完整。抛超时前做最后一次完整 done 判定 + 抓内容;确失败才 retry ×1。
- **中断分类**:失败原因枚举加「中断(睡眠唤醒/wall-clock 跳变)」类,不喂短路计数、不 retry。
- **轮询降本**:3 lane 并发后每 500ms 两次整页 `page.content()`+bs4 会打满 GIL。done 判定改 `page.evaluate` 取答案容器 `textContent.length`,bs4 只在结束后跑一次。

### 4.4 错误分类 + 真实原因传导(治「一律够不到平台」)

- **后端**:异常归类枚举 `fail_reason ∈ {not_logged_in, timeout, selector_drift, rate_limited, quota_exhausted, content_blocked, network, interrupted, unknown}`。
- **持久化**:新增 `geo_cells.fail_reason` 列(v10 迁移,`_ensure_column` 幂等回填,链式迁移已验证支持);同时 raw_json 继续存原始 error 文本。`status` 仍限 `{ok,empty,blocked,error}` 不变(保住 `isFailed` 与既有测试)。
- **前端**:`RawCell`/`cellToPlatform` 增读 `fail_reason`,卡片副标题按 code 映射人话:「未登录·去登录」「超时·可重试」「限流/欠费·查配额」「内容风控」「已中断」等,替掉写死的「够不到平台」。

### 4.5 合成 cell:被跳过的平台绝不缺席(致命修复②)

- 无论是 gate 首格 blocked 跳过、还是连败短路跳过,**该平台余下每个关键词都要写一条合成 cell**(`status=blocked`,带 `fail_reason`),不能缺席。
- 原因:前端 `placeholderPlatform` 会把缺 cell 的平台渲染成 `pending`「未运行/待采集」(`geoDetail.ts:377`),L1「部分失败」标记靠 `error_cells>0`(`GeoTaskModule.vue:142`),全平台被跳时 `if cells and ok_cells==0` 守卫失效会假报「监测完成」(`geo_query.py:122`)。合成 cell 让这三条契约继续成立。
- `alerts.py:41` 的 `platform_dropped` 有 `ok_total>0` 守卫,合成 blocked cell 不会触发假「跌出」告警。

### 4.6 多次采样(数据更准,修正为轻量默认)

- **默认 K=1**(修正 K=3):同一分钟连采共享同一批搜索结果,样本高度相关,多数投票只磨温度噪声,磨不掉日间排名抖动。
- **翻转复核**:当本轮结论与上一轮**翻转**(提及↔未提及)时,自动补采 1 次确认。
- **投票只用于判定,不用于信源(致命修复④)**:mention 多数票、rank 取命中样本中位(`int()` 强转以匹配 `rank INTEGER`)、sentiment 多数(3 路平局回退 `na`);**citations/信源只取第一个成功样本**,口径与今天完全一致,避免并集把 `geo_citations` 行数×K 放大污染信源榜权重(`storage.py:161` weight=count×平台×权威)与卡片「引用 N」。
- **形状保持**:`extraction_json` 仍为 `{recommended:[...], summary:str}`(L2 钻取/竞品聚合读它,`storage.py:221`);样本明细放没人读的 `raw_json`。
- K、翻转复核开关走 per-task `config_json`,增量、对旧任务向后兼容。
- 趋势 UI 加 7 天滚动中位线(零成本的跨天稳定器)。

### 4.7 分母口径/完整度(增量,不改语义,不加状态)

- **不新增 partial 运行状态(致命修复③)**:`MonitorStatus` Literal 会 ValidationError;monitor_loop 把非 ok 一律发 `failed`;GEO 告警在 `status!="ok"` 整体哑火;L1 徽标漏原串。
- 改为在 metric 里**增量附加** `platforms_expected` / `platforms_measured` / `completeness`,前端展示「本次基于 N/5 平台」+ 数据完整度指示。
- SoC/首推率分母**维持** `ok_total` 语义不变(不把失败折进分母,否则破 `test_geo_exposure_summary`、`exposure_window` 硬编码 `status='ok'`)。完整度是独立信号,不是分母变更。

### 4.8 API 车道细节

- per-provider 复用 `httpx.Client`(线程安全,连接池)。
- 有界并发池(4–5)。
- **429 豁免**:仓库 §9「API 不自动重试」立法本意防重复计费,而 429/连接建立失败**不计费** → 允许带 Retry-After 单次重试;已开始生成的响应绝不重发。tongyi/doubao 采集调用保持无其他重试。
- extract 路径既有的 tenacity ×3 + 坏 JSON 二次调用是既存事实,spec 承认并保留(小额),不声称「API 零重试」。

---

## 5. 数据模型变更

- `geo_cells` 新增列 `fail_reason TEXT`(v10 迁移,`_ensure_column` 幂等)。
- `geo_cells.raw_json` 增量键:`samples`(多样本明细)、保留 `error`。无严格 key 迭代的读者(`_hydrate_cells` 用 `.get`,前端 `RawCell` 忽略 raw_json),向后兼容。
- `extraction_json` 形状不变。
- metric blob 增量键:`platforms_expected/measured/completeness`。
- 注意 `raw_json` 存整包响应,K 采样后年增量约百 MB 级——顺带项,暂不治理。

---

## 6. 配置面(per-task config_json + AppConfig.monitor,均增量)

| 键 | 默认 | 说明 |
|---|---|---|
| `geo_sample_count` (K) | 1 | 每格采样数 |
| `geo_flip_recheck` | true | 与上轮翻转时补采 1 次 |
| `geo_api_pool_size` | 5 | API 车道并发上限 |
| `geo_rpa_platform_concurrency` | 3 | 同时并发的 RPA 平台数(低配可降到 1) |
| `geo_rpa_jitter_min/max` | 15 / 45 s | 答后思考间隔 |
| `geo_start_jitter_max` | 20 min | 定时任务随机启动延迟 |
| `geo_rpa_retry` | 1 | 超时验尸后重试次数 |
| `geo_consecutive_fail_skip` | 3 | 连败短路阈值 |
| `geo_run_window_hours` | (可选) | 迟到超过则跳过/降级 |

旧任务缺这些键时全部走默认,`GeoTaskConfig` interface 容忍额外键,无版本破坏。

---

## 7. 测试与验收

- **单测**:双车道调度(mock provider,验并发不破乱序契约 + 进度单调)、错误分类映射、多样本聚合(含 mention 分裂/sentiment 平局/rank 中位取整)、翻转复核、合成 cell 生成、完整度字段、429 carve-out。
- **回归**:跑通现有 4 个 Python 测试 + 前端 `geoDetail.spec.ts`;凡被 v2 语义改动的断言(如进度、subtitle)同步更新并说明理由。
- **真机**:对用户真实任务跑一次,验证 ①RPA 三平台不再假失败 ②一轮墙钟落到 ~1h ③卡片显示真实原因 ④信源榜「引用 N」口径未虚高。
- **对抗性审查**:完成前按用户全局规则再派 2–3 独立 subagent(正确性/回归/资源竞争与风控)证伪,发现逐条核实。
- 注意:`sidecar/tests/` 不在默认 pytest 与 CI 里跑,需显式 `pytest sidecar/tests/`。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| RPA 站点 DOM 改版 → 选择器再漂 | 多候选选择器 + Enter 兜底 + 真实原因暴露便于快速定位 |
| 27 连问触发单账号软封(尤其 Kimi 免费档) | 每题 goto 重置 + 15–45s jitter + 顺序洗牌 + 启动抖动;元宝建议用 QQ 号登录隔离微信资产 |
| 3 个 headed Chrome 本机资源(~2–3GB RAM) | `geo_rpa_platform_concurrency` 可降到 1;冷启错峰 10–20s |
| 睡眠唤醒错误风暴 | 中断分类 + 超时前验尸 + run-window 守卫 |
| 豆包联网插件按检索次数计费,方差大 | 上线首周核对火山 `action_usage` |

---

## 9. 后续专项(不在本次范围)

- **专项 C:去 RPA 化调研**——评估 2026 年 Kimi/DeepSeek/元宝 的官方联网 API 是否已能返回信源 URL,或引入第三方 GEO 数据源;RPA 仅作兜底。需独立 spec + 可行性验证。
