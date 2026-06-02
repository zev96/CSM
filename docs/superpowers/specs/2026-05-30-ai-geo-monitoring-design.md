# AI 卡位监控（GEO 监控）· 设计

- 状态：已与用户对齐，待生成实施计划
- 日期：2026-05-30
- 工作树：`.claude/worktrees/elated-bhaskara-1aeaf1`（分支 `claude/elated-bhaskara-1aeaf1`）
- 相关代码栈：Tauri shell + Vue 前端 + Python sidecar，沿用 `csm_core/monitor/` 现有平台 adapter 范式
- 别名：GEO（Generative Engine Optimization）监控 / Share-of-Chat 监控

## 1. 目标与边界

在「监测中心」新增一种监控类型 `geo_query`：批量关键词 → 自动采集主流 AI 平台对这些关键词的回答 → 结构化提取品牌的**曝光度、首推率、情感、引用信源**，并把高权重信源聚合成「精准喂饭」目标清单。

**覆盖 6 个 AI 平台（3 API + 3 RPA）：**

| API 层（阶段 1–2） | RPA 层（阶段 3） |
|---|---|
| 通义千问 · Kimi · 豆包 | DeepSeek · 夸克AI · 腾讯元宝 |

**做什么：**

- 一个任务 = 一个**品牌** × 一组**关键词** × 一组**平台**，任务内部 `关键词 × 平台` fan-out
- 采集每个 cell 的 AI 完整回答 + 引用信源（联网搜索开启）
- LLM 抽取每条回答为结构化 `{提及, 顺位, 情感, 推荐列表, 信源}`
- 算四大 KPI：曝光度(Share of Chat) / 首推率 / 情感得分 / 引用信源榜
- 监测中心看「最近一次」；数据中心看「趋势 + 聚合信源榜（可导出 Excel）」
- 信源榜预留「去引流中心铺这个源」闭环入口

**非目标（明确不做）：**

- **不做竞品对标 / 竞品份额**——单品牌追踪。会抽出「AI 推荐了哪些品牌的有序列表」用于定位本品牌顺位，但不维护竞品名册、不算竞品 SOV（推荐列表里的竞品名只展示、不追踪）。
- **v1 不做信源「品牌级归因」**（不标注「这条源在夸你 vs 夸竞品」）——先做扎实「收集 + 分类 + 聚合」。归因留作后续增强。
- **DeepSeek 不走官方 API**——官方 API 不联网、拿不到信源，所以 DeepSeek 走 RPA（chat.deepseek.com 联网）。
- 不做实时/高频监控——GEO 一次运行成本高（API 费用 + RPA 时长），默认 manual / weekly，不提供 hourly。
- 不在 v1 实现「自动铺内容」——信源榜 → 引流中心只做跳转带参，实际铺内容动作复用引流中心既有能力，分阶段深接。

## 2. 关键决策（已与用户对齐）

| 维度 | 决策 |
|---|---|
| 采集策略 | **API 优先、RPA 兜底**（省成本）。能用 API 稳定拿联网信源的走 API，拿不到的走 RPA |
| 监控目标 | **单品牌追踪**（非竞品对标） |
| 平台划分 | API：通义/Kimi/豆包；RPA：DeepSeek/夸克/元宝 |
| API 密钥 | 用户已有或愿申请 Kimi(Moonshot) / 通义(DashScope) / 豆包(火山方舟 Ark) |
| 顺位抽取 | **LLM 抽取**（复用 `csm_core/llm/` 现有 client），非正则 |
| 整体结构 | **扩展现有 monitor 模块**（加 `geo_query` 任务类型 + `monitor/geo/` 子包），全复用 storage/loop/SSE/凭证池/批量 |
| 任务粒度 | 一品牌一任务，任务内 `关键词 × 平台` fan-out |
| 首推率分母 | **总 cell 数**（对任意查询被摆第一的绝对概率）；另出「提及内首推率」做细分 |
| 顶层 rank | 存「提及 cell 的中位顺位」喂现有告警/趋势轨道；真正头条是四大 KPI |
| 隐身线 | **曝光度 < 20% = 隐身**（红），20–50% 弱势（黄），> 50% 优势（绿）；< 20% 触发告警 |
| 存储 | `monitor_results.metric_json` 存运行级 KPI 汇总；新增 `geo_cells` / `geo_citations` 规范化表供聚合（schema v7） |
| 信源分类 | 域名规则表优先，未命中 LLM 兜底 |
| UI 落点 | **监测中心 tab「AI 卡位」跑任务 + 数据中心 sub-pivot「AI 卡位」看分析**（对齐 zhihu/baidu 现有拆法） |
| 调度 | 复用 scheduler，默认 manual / weekly；不提供 hourly |

## 3. 架构与模块边界

### 3.1 后端（Python）

```
csm_core/monitor/
├── base.py                      ← TaskType Literal 加 "geo_query"
├── storage.py                   ← _migrate() 加 apply_v7_migration（懒加载，仿 mining）
├── platforms/
│   ├── __init__.py              ← 注册 GEO adapter 到 ALL
│   └── geo_query.py             ← 新增：GeoQueryAdapter（fan-out + 进度 + 续抓 + 取消）
└── geo/                         ← 新增子包
    ├── __init__.py
    ├── models.py                ← GeoAnswer / Citation / GeoExtraction / RecommendedEntity / ClassifiedCitation
    ├── providers/
    │   ├── base.py              ← GeoProvider Protocol + 注册表
    │   ├── api_tongyi.py        ← 通义 DashScope enable_search
    │   ├── api_kimi.py          ← Kimi Moonshot $web_search
    │   ├── api_doubao.py        ← 豆包 火山方舟 Ark 联网
    │   ├── rpa_base.py          ← RPA provider 基类（流式完成检测 + 信源 DOM 抽取）
    │   ├── rpa_deepseek.py      ← chat.deepseek.com 联网
    │   ├── rpa_quark.py         ← quark.cn AI 搜索
    │   └── rpa_yuanbao.py       ← yuanbao.tencent.com
    ├── extract.py               ← LLM 抽取管线（GeoAnswer → GeoExtraction）
    ├── classify.py              ← 域名规整 + source_type 分类（规则表 + LLM 兜底）
    ├── metrics.py               ← 四大 KPI 聚合（cells → KPI 汇总块）
    └── storage.py               ← geo_cells/geo_citations DDL + apply_v7_migration + 聚合查询

sidecar/csm_sidecar/
├── routes/monitor.py            ← 泛型 task 路由已覆盖 CRUD/run-now/cancel/resume/events；
│                                  仅新增 GEO 专用聚合只读端点（见 §8.3）
├── services/monitor_loop.py     ← 不动（adapter 动态分发已覆盖）
└── services/monitor_lifecycle.py← 启动时配置 GEO provider（API key / 凭证）
```

**复用、零改动的现有基建：** `monitor_loop`（调度/线程池/进度/取消/续抓/SSE）、`scheduler`、`monitor_tasks`/`monitor_results` 表、`platform_credentials` 凭证池（cookie 轮换 + cooldown）、`drivers/`（PatchrightDriver + pool）、`llm/`（抽取 client）、`notify`（告警）。

### 3.2 前端（Vue）

```
frontend/src/
├── components/monitor/
│   ├── AddTaskModal.vue                 ← +geo_query 分支（品牌/别名/关键词批量/平台多选/联网/抽取LLM）
│   ├── BatchImportTaskModal.vue         ← +GEO 关键词 Excel 模板（可选）
│   ├── CookieManagerModal.vue           ← +GEO RPA 平台（deepseek/quark/yuanbao）登录入口
│   └── geo/
│       └── GeoTaskModule.vue            ← 监测中心「AI 卡位」tab：任务列表 + run + 进度 + 最近一次 KPI 快照
├── components/monitor/history/
│   └── GeoAnalyticsPage.vue             ← 数据中心「AI 卡位」pivot：卡位矩阵 + 趋势 + 信源榜 + 导出 + 下钻
├── views/MonitorView.vue                ← +「AI 卡位」tab
├── views/DataCenterView.vue             ← +「AI 卡位」sub-pivot
└── utils/monitor-types.ts               ← +GeoTask / GeoKpi / Citation 类型
```

**IA 注记：** UI 按**当前** IA 约定落点（监测中心跑 + 数据中心看）。因项目计划做 B+C 大改（IA 重做），GEO UI 全部做成**自包含组件**（`GeoTaskModule` / `GeoAnalyticsPage`），IA 重做时整块挪位、不返工。GEO 的数据/存储/采集/抽取层与 IA 无关、不受影响。

### 3.3 GeoQueryAdapter 内部分层

```
GeoQueryAdapter.fetch(task, progress_cb, cancel_token, resume_from)
  ├─ 解析 config → brand/aliases/keywords[]/platforms[]/web_search/extract_provider
  ├─ cells = product(keywords, platforms)，按 resume_from 跳过已完成
  ├─ for i, (kw, plat) in enumerate(cells[resume_from:]):
  │     maybe_cancel(cancel_token)
  │     with slot(plat):                       # 复用 per-platform 限流信号量
  │         answer = providers[plat].query(kw, web_search=..., cancel_token=...)
  │     log raw（http/len/first500，silent-failure 防御）
  │     extraction = extract(answer, brand, aliases, provider=extract_provider)
  │     extraction.citations = classify(extraction.citations)
  │     记录 cell（内存累积；阶段性 flush 到 geo_cells/geo_citations）
  │     progress_cb(resume_from + i + 1, total)
  ├─ kpi = metrics.aggregate(cells)            # 四大 KPI 汇总块
  └─ return MonitorResult(status, rank=中位顺位, metric={kpi, summary_refs})
        # 明细 cell/citation 由 storage.record_run 落规范化表
```

- **cell 级错误隔离**：单 cell 失败（API 错 / RPA 挡 / 验证码 / 抽取坏 JSON）记 `status=error|blocked` 并继续，运行以部分数据完成。
- **风控**：RPA cell 命中登录失效/验证码/风控 → 抛 `_RiskControlException`（复用现有），存断点 + cookie cooldown，UI 可 resume。

## 4. 任务形态与数据模型

`config_json`：

```jsonc
{
  "brand": "小鹏",
  "brand_aliases": ["XPeng", "小鹏汽车", "P7"],   // 命中与抽取归一都用
  "keywords": ["20万左右新能源车推荐", "智驾最好的车"],  // 批量，一行一个
  "platforms": ["tongyi","kimi","doubao","deepseek","quark","yuanbao"],
  "web_search": true,
  "extract_provider": "deepseek",                  // 用哪个 LLM 抽取
  "top_n_citations": 20
}
```

- `target_url`：合成键 `geo://<brand>` 满足现有 `UNIQUE(type, target_url)` 去重约束 + 非空校验。
- `name`：用户自定义，如「小鹏·新能源关键词卡位」。
- fan-out 总数 = `len(keywords) × len(platforms)`，作为进度分母。

## 5. 采集层（GeoProvider）

### 5.1 接口

```python
class Citation(BaseModel):
    url: str
    title: str = ""

class GeoAnswer(BaseModel):
    platform: str
    keyword: str
    answer_text: str                  # 完整回答（已等流式结束）
    citations: list[Citation]         # 原始信源（API annotation 或 DOM 抽取）
    raw: dict                         # 原始响应留档（排障）
    status: Literal["ok","empty","blocked","error"]
    error: str = ""

class GeoProvider(Protocol):
    platform: str
    mode: Literal["api","rpa"]
    def query(self, keyword: str, *, web_search: bool, cancel_token) -> GeoAnswer: ...
```

### 5.2 六平台落点

| 平台 | 方式 | 关键点 | 信源来源 |
|---|---|---|---|
| 通义千问 | API | DashScope `enable_search=true` + `search_options` | response search/annotations |
| Kimi | API | Moonshot OpenAI 兼容 + `$web_search` builtin（function-call 回路） | tool 返回 search results |
| 豆包 | API | 火山方舟 Ark 联网 endpoint（控制台开联网） | response references |
| DeepSeek | RPA | chat.deepseek.com 开联网，Patchright 驱动 | DOM 引用脚注 |
| 夸克AI | RPA | quark.cn AI 搜索，Patchright | DOM 信源卡 |
| 腾讯元宝 | RPA | yuanbao.tencent.com，微信/QQ 登录，Patchright | DOM 参考资料 |

### 5.3 阶段 1 Task 0：API 信源探针（强制前置）

三家 API 的「联网 + 回信源」字段格式有把握但非 100% 锁定（厂商会变）。**实施第一步**：对通义/Kimi（阶段 1）、豆包（阶段 2）各发一个真实联网请求，确认：

1. 联网是否真的触发、回答里有没有 web 内容
2. 信源（URL + 标题）从哪个字段拿、结构长啥样
3. **实测拿不到信源的平台 → 当场降级到 RPA**（provider 抽象对上层无感）

探针产出的真实响应存为 fixture，供抽取/分类的离线单测使用。

### 5.4 RPA provider 通用要点（阶段 3）

- 复用 PatchrightDriver + patchright_pool + 凭证池 + cooldown。
- **流式完成检测**：等「停止生成 → 重新生成」按钮切换，或 DOM 稳定 + 网络空闲启发式，带超时。
- **信源 DOM 抽取**：每平台一段 `evaluate_js` 一次性 bulk 抽（一次往返），沿用项目既有 page.evaluate 套路。
- **登录**：复用 `interactive_login`（Patchright 可见窗），cookie 持久化进凭证池，cooldown 时轮换。
- 拟人 pacing（复用 `rate_limit`），每平台 `slot=1`，默认 weekly，节制频率。

## 6. 抽取层

### 6.1 输出模型

```python
class RecommendedEntity(BaseModel):
    name: str          # AI 推荐列表里的一个品牌/产品
    position: int      # 1-based
    is_target: bool    # 是否=追踪品牌（别名归一后判定）

class ClassifiedCitation(BaseModel):
    url: str
    title: str = ""
    domain: str        # 规整出的注册域名
    source_type: str   # 知乎/小红书/权威媒体/官网/电商/其他

class GeoExtraction(BaseModel):
    mentioned: bool
    target_rank: int                     # -1=未提及/未进推荐列表
    sentiment: Literal["pos","neu","neg","na"]
    recommended: list[RecommendedEntity] # 完整有序推荐列表（含竞品，单品牌模式只展示）
    citations: list[ClassifiedCitation]
    summary: str                         # 一句话：AI 怎么评价该品牌
```

### 6.2 实现

- 一次 LLM 调用产出 mentioned/rank/recommended/sentiment/summary（结构化 JSON 输出），`make_client(provider=config.extract_provider)`。
- 坏 JSON → 严格 prompt 重试一次 → 仍失败降级（启发式 mentioned + rank=-1）并标「待人工复核」。
- 别名归一：brand + brand_aliases 统一小写/去空格后判定 `is_target`。

### 6.3 信源分类（classify.py）

- `domain`：取注册域名（tldextract 或等价逻辑）。
- `source_type`：**规则表优先**——`zhihu.com→知乎`、`xiaohongshu.com→小红书`、`gov.cn`/主流媒体域名表`→权威媒体`、品牌官网`→官网`、`jd.com`/`tmall.com`/`taobao.com→电商`；规则未命中再让 LLM 兜底归类（省 token、稳定）。

## 7. 指标口径（四大 KPI）

一次运行产出 `cells = 关键词 × 平台`，每 cell 抽出 `{mentioned, rank, sentiment, citations[]}`。

| KPI | 公式 | 维度 | 阈值/告警 |
|---|---|---|---|
| **① 曝光度 Share of Chat** | 提及 cell 数 / 总 cell 数 | 整体 · 按平台 · 按关键词 | **<20% 隐身(红)**，20–50% 弱势(黄)，>50% 优势(绿)；<20% 触发隐身告警 |
| **② 首推率** | rank==1 cell 数 / **总 cell 数** | 整体 · 按平台 · 按关键词 | 另算「提及内首推率」=rank==1/提及数；附顺位分布(#1/Top3/Top5/提及未进榜/未提及) |
| **③ 情感得分** | pos=+1,neu=0,neg=−1，对提及 cell 取均值 → **净情感分∈[−1,+1]** | 整体 · 按平台 | 同时展示 正/中/负 占比；负向占比高触发预警 |
| **④ 引用信源榜** | domain 频次降序 + 分类 + 命中关键词 + 出现平台 | 跨关键词 · 跨平台 · 跨时间 | —（产出，非告警） |

- 顶层 `MonitorResult.rank` = 提及 cell 的中位顺位（无提及则 -1），仅供现有告警/趋势轨道。
- 运行级 KPI 汇总块写入 `metric_json`，仪表盘秒开。

## 8. 存储

### 8.1 规范化表（schema v7）

```sql
CREATE TABLE IF NOT EXISTS geo_cells (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  result_id INTEGER NOT NULL REFERENCES monitor_results(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL,
  checked_at TEXT NOT NULL,
  platform TEXT NOT NULL,
  keyword TEXT NOT NULL,
  mentioned INTEGER NOT NULL DEFAULT 0,
  rank INTEGER NOT NULL DEFAULT -1,
  sentiment TEXT NOT NULL DEFAULT 'na',
  answer_text TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ok',
  raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS geo_citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cell_id INTEGER NOT NULL REFERENCES geo_cells(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL,
  checked_at TEXT NOT NULL,
  platform TEXT NOT NULL,
  keyword TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  domain TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL DEFAULT '其他'
);
CREATE INDEX IF NOT EXISTS idx_geo_cit_task_domain ON geo_citations(task_id, domain);
CREATE INDEX IF NOT EXISTS idx_geo_cells_task_time ON geo_cells(task_id, checked_at DESC);
```

DDL + `apply_v7_migration(conn)` 放 `csm_core/monitor/geo/storage.py`，由 `monitor/storage.py::_migrate` 懒加载调用（仿现有 mining v3–v6 模式），`_SCHEMA_VERSION` 提到 7。

### 8.2 聚合查询（geo/storage.py）

- `record_run(result_id, task_id, cells)` — 批量插 geo_cells + geo_citations。
- `kpi_summary(task_id, window)` — 四大 KPI（整体 + 按平台 + 按关键词）。
- `citation_leaderboard(task_id, days, platform?, keyword?)` — `SELECT domain, source_type, count(*) ... GROUP BY domain ORDER BY 3 DESC`，附命中关键词/平台聚合。
- `cells_for_run(result_id)` / `cell_detail(cell_id)` — 下钻看原文 + 该答案信源。
- `soc_trend(task_id, days)` / `first_rank_trend(task_id, days)` — 趋势。

### 8.3 新增只读端点（routes/monitor.py）

- `GET /api/monitor/geo/{task_id}/kpi?window=...`
- `GET /api/monitor/geo/{task_id}/citations?days=&platform=&keyword=`
- `GET /api/monitor/geo/{task_id}/cells?result_id=`（下钻）
- `GET /api/monitor/geo/{task_id}/export`（信源榜 Excel）

任务 CRUD / run-now / cancel / resume / events 复用现有泛型路由，**不新增**。

## 9. 调度与告警

- 复用 scheduler，`schedule_cron`：manual / daily / weekly（不提供 hourly）。
- 复用 `notify.should_alert`，扩展 `geo_query` 分支：
  1. **隐身**：整体或某平台 SoC < 20%
  2. **首推率下滑**：本次首推率较上次显著下降
  3. **掉出**：某平台从「提及」变「未提及」
- 成本/时长预期：10 关键词 × 6 平台 ≈ 60 cell，含 3 个 RPA ≈ 10 分钟级（RPA 串行 + ~20s/条）。每 cell = 1 采集 + 1 抽取 LLM。

## 10. 前端 UI

### 10.1 监测中心 · tab「AI 卡位」（GeoTaskModule.vue）—— 操作面

- **建任务**（AddTaskModal geo 分支）：品牌 + 别名 + **关键词批量 textarea（一行一个）** + 平台 6 选 + 联网开关 + 抽取 LLM 选择 + 调度。
- **L1 任务列表**：品牌 / 关键词数 / 平台数 / 上次运行 / SoC / 首推率 + run·编辑·删除。
- **运行**：run-now + SSE 实时进度（cell x/60 + 各平台状态）。
- **最近一次快照**：4 KPI 卡 + 最近一次信源榜 Top。
- **RPA 登录**：复用 CookieManagerModal，deepseek/quark/yuanbao 走交互式登录。

### 10.2 数据中心 · sub-pivot「AI 卡位」（GeoAnalyticsPage.vue）—— 分析面

- 与「知乎排名 / 平台评论 / 百度排名」并列新增「AI 卡位」pivot。
- **4 KPI 卡**：SoC（含隐身/弱势/优势色带）/ 首推率（+顺位分布条）/ 净情感分（+占比）/ 信源榜 Top。
- **卡位矩阵**：平台 × {SoC, 首推率, 情感} 热力表。
- **趋势 sparkline**：SoC / 首推率随时间。
- **信源聚合榜表格**：domain · 分类 · 频次 · 命中关键词 · 出现平台；按平台/关键词筛选；**「导出信源榜」Excel** 按钮；每行预留**「去引流中心铺这个源」**入口（带 domain/关键词跳 MiningView）。
- **下钻**：点矩阵某格 → 该 (关键词,平台) 的 AI 原文 + 信源 → `@navigate` 跳回监测中心任务。

### 10.3 闭环（产品愿景）

信源榜高频域名（知乎/小红书）正是引流中心已在挖的平台。信源榜行 →「去引流中心铺这个源」→ 带 domain/关键词跳进 MiningView，把「发现高权重源 → 去铺 E-E-A-T 内容」接成闭环。v1 只做跳转带参；实际铺内容动作复用引流中心既有能力，阶段 2–3 深接。

## 11. 错误处理 / 反爬 / 凭证

- **cell 级隔离**：单 cell 失败不拖垮整次运行，记 status 继续，部分数据完成（复用 baidu 部分合并 + 续抓）。
- **API**：瞬时错误走现有 tenacity 重试；鉴权错误明确报出。
- **RPA**：登录失效/验证码/风控 → cell 记 blocked + 抛 `_RiskControlException` 暂停存断点 + cookie cooldown，UI 可 resume。
- **Silent-failure 防御**（项目教训）：每 provider 每 cell 一开始就 `log http/len/first500`，`raw_json` 落库 → 「0 提及」能分辨 cookie 失效 / 真没提及 / schema 变 / 风控。
- **抽取失败**：坏 JSON 重试一次 → 降级 + 标待复核。

## 12. 测试策略（走项目 TDD）

- **单元**：抽取（黄金答案 fixture → 期望 GeoExtraction）、域名分类规则表、**KPI 聚合**（cells fixture → 期望 SoC/首推率/情感分）、信源榜聚合查询。
- **Provider 契约**：用 §5.3 探针录制的真实响应 fixture 离线测，不打活 API。
- **Invariant**：`geo_query` 在全部注册落点都注册（base.py Literal / platforms/__init__ / 前端 TYPES）。
- **集成**：mock GeoProvider + in-memory sqlite → 全链路 fetch() → metric/表断言。

## 13. 分阶段交付

### 阶段 1 · 核心闭环（API ×2：通义 + Kimi）

0. **API 信源探针**（§5.3，强制前置；实测无信源则降级 RPA）
1. `geo_query` 任务类型全链路注册（+ invariant 测试）
2. GeoProvider 抽象 + 通义 + Kimi 两个 API provider
3. LLM 抽取管线 + 域名分类规则表 + 四大 KPI 聚合
4. `geo_cells` / `geo_citations` 表（v7 migration）
5. 监测中心「AI 卡位」tab（建任务 + run + SSE 进度 + 最近一次 4 KPI 卡 + 信源榜）
6. 数据中心「AI 卡位」pivot 最小版（4 KPI 卡 + 信源榜表）

**交付**：真实关键词跑通通义/Kimi，看到 SoC/首推率/情感/信源榜。**验证抽取准确率（人工抽查 N 条）+ 信源价值。**

### 阶段 2 · 补齐 API + 产品化

- 豆包 Ark provider（先跑探针）
- 卡位矩阵 + 趋势 sparkline + 信源榜筛选/导出 Excel + 下钻原文
- 调度（weekly/daily）+ 三类告警 + 隐身线
- 信源榜「去引流中心」跳转带参

### 阶段 3 · RPA 层（DeepSeek → 夸克 → 元宝）

- RPA GeoProvider 基类（流式完成检测 + 信源 DOM 抽取 + 登录/cookie 复用）
- **DeepSeek（登录/反爬最温和，先做）→ 夸克 → 元宝（微信登录最重，最后）**
- CookieManagerModal 接入 GEO 平台登录
- 每平台 raw-logging + cooldown + 风控暂停/续抓

## 14. 风险与开放问题

- **API 信源能力会变**：靠 §5.3 探针前置 + provider 抽象降级兜底。
- **RPA 反爬强度**（腾讯/夸克/阿里系）：靠 patchright stealth + 拟人 pacing + 节制频率 + cooldown；元宝微信登录最重，放最后。
- **抽取准确率**：阶段 1 末人工抽查校准 prompt；坏 JSON 降级 + 待复核兜底。
- **成本**：每 cell = 1 采集 + 1 抽取 LLM；默认 manual/weekly + 限流控总量。
- **IA 大改**：UI 自包含组件，IA 重做整块挪位；数据层不受影响。
- **开放**：①豆包 Ark 是否需要预建联网 bot/endpoint（探针确认）；②元宝/夸克信源 DOM 选择器需实测（阶段 3 spike）；③首推率头条若想用「提及内」版本，一行配置切换。
