# 视频引流抓取（Video Mining）MVP — 设计稿

- 日期：2026-05-16
- 范围：本 spec 仅覆盖 MVP（① 关键词 → 3 平台搜索抓视频列表页字段；③ 全局去重落库）。视频内容 AI 总结、评论库管理、外派对接、监控同步留作后续 spec。

---

## 1. 背景与边界

### 1.1 上下文
CSM 现有：

- `csm_core/monitor/` —— 5 个平台（抖音/B站/快手/知乎/百度）的"评论留存监控"模块，输入是已知视频 URL，输出是"我自己发的评论现在排第几"。
- `csm_core/monitor/drivers/` —— `patchright_pool`、`cookie_store`、`ua_pool`、`rate_limit` 已稳定。
- `csm_core/monitor/storage.py` —— SQLite 存储（monitor 任务/结果/凭据/AI enrichment）。
- 前端 Tauri + Vue3 + Pinia，已有 `MonitorView`。

引流的核心目标是"**从关键词找潜在投放视频**"，与"评论留存监控"是不同语义的工作流，因此独立模块、独立 view。

### 1.2 MVP 范围（in scope）

- 用户在前端输入一个关键词，可选三平台（抖音 / B 站 / 快手），起一次后台任务。
- 任务每平台抓 ≈50 条搜索结果（默认值），仅取搜索列表页字段。
- 抓到的视频流式落 SQLite，全局按 `(platform, platform_video_id)` 去重。
- 视频在前端展示为可筛选/搜索的库表，可导出 CSV。

### 1.3 非范围（out of scope）

- 视频详情页二次抓取与字段补全（第二期 enrich）。
- 视频内容的 AI 文本总结（独立横切关注点，第二期）。
- 评论计划数据结构与评论编辑 UI（第二期）。
- 外派任务对接（腾讯文档 / 飞书 Base，第三期）。
- 与 `monitor_tasks` 评论留存监控的双向同步（第二期）。

### 1.4 验收标准

- 输入关键词 "扫地机器人"，三平台抓回 ≥100 条且零重复（按 `(platform, platform_video_id)` 唯一）。
- 任务跑完总耗时 5–10 分钟（每平台串行、各 1–3 分钟）。
- 任意时刻可点取消，已抓到的数据保留不回滚。
- 抖音 cookie 过期时不阻塞其他平台，job 整体 `status=partial_done`，对应平台 `needs_login`。
- 同关键词二次起任务，不出现重复 `videos` 行（仅追加 `video_source_keywords`）。

---

## 2. 已锁定的关键决策

| 项 | 决策 |
|---|---|
| 单次规模 | 每平台默认 50 条（前端可调，上限 200） |
| 任务模型 | 单关键词 → 单任务；后台异步；三平台**串行**跑（一次只起一个 patchright 实例） |
| 抓取深度 | 仅列表页字段，不进详情页 |
| 去重粒度 | 全局 `(platform, platform_video_id)` 唯一；多关键词命中只记 `video_source_keywords` |
| 浏览器模式 | **有头 + 独立 user-data-dir + 首次手动登录**（窗口跑期间可弹出，能最小化） |
| 前端入口 | 新建独立 `MiningView`，LeftNav 顶级入口"引流" |

---

## 3. 模块结构

```
csm_core/
├── browser_infra/                  ← 从 monitor 上提的共享基建（重构）
│   ├── __init__.py
│   ├── cookie_store.py             ← 原 monitor/drivers/cookie_store.py
│   ├── ua_pool.py                  ← 原 monitor/drivers/ua_pool.py
│   ├── rate_limit.py               ← 原 monitor/rate_limit.py
│   ├── patchright_pool.py          ← 原 monitor/drivers/patchright_pool.py
│   └── interactive_login.py        ← 原 monitor/drivers/interactive_login.py
│   * monitor 包内保留薄 re-export 模块，确保现有 import 不破
│
└── mining/                         ← 新模块
    ├── __init__.py
    ├── models.py                   ← MiningJob / Video / SourceKeyword pydantic
    ├── storage.py                  ← 三表 + schema migration v2 → v3
    ├── runner.py                   ← 后台 worker：跑一个 MiningJob
    ├── extract.py                  ← 公共字段提取/规整工具
    └── platforms/
        ├── __init__.py
        ├── _common.py              ← 平台适配器 Protocol、VideoCard dataclass
        ├── douyin_search.py
        ├── bilibili_search.py
        └── kuaishou_search.py

sidecar/csm_sidecar/
├── routes/mining.py                ← FastAPI 路由
└── services/mining_service.py      ← 业务编排 + 事件总线对接

frontend/src/
├── views/MiningView.vue
├── components/mining/
│   ├── StartJobModal.vue           ← 新任务弹窗
│   ├── VideoTable.vue              ← 视频库表
│   ├── JobProgressCard.vue         ← 进行中任务进度卡
│   └── PlatformLoginPanel.vue      ← 平台登录状态面板
└── stores/mining.ts                ← Pinia store
```

**关键设计点：**

- `browser_infra` 的提取是顺手清理，不是激进重构。monitor 包内对应文件改为薄 re-export（如 `from csm_core.browser_infra.cookie_store import *`），现有 import 路径全部不破。
- mining 不蹭 monitor 的调度（mining 是一次性 job，不需要 cron）。
- mining 与 monitor 共用同一份 SQLite 文件，避免新建第二个 db。

---

## 4. 数据模型

迁移到 `_SCHEMA_VERSION = 3`，新增三张表：

```sql
-- 任务表：一次"输入关键词+起跑"对应一行
CREATE TABLE mining_jobs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  keyword         TEXT NOT NULL,
  platforms_json  TEXT NOT NULL,              -- ["douyin","bilibili","kuaishou"]
  target_per_platform INTEGER NOT NULL DEFAULT 50,
  status          TEXT NOT NULL,              -- pending|running|done|partial_done|failed|cancelled|interrupted
  progress_json   TEXT NOT NULL DEFAULT '{}', -- 每平台 {"got":N,"target":M,"phase":"scrolling|done|failed|needs_login"}
  error_message   TEXT NOT NULL DEFAULT '',
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  started_at      TEXT,
  finished_at     TEXT
);
CREATE INDEX idx_mining_jobs_keyword ON mining_jobs(keyword);
CREATE INDEX idx_mining_jobs_created ON mining_jobs(created_at DESC);

-- 视频表：全局去重的实体
CREATE TABLE videos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  platform        TEXT NOT NULL,              -- douyin|bilibili|kuaishou
  platform_video_id TEXT NOT NULL,            -- aweme_id / bvid / photoId
  url             TEXT NOT NULL,
  title           TEXT NOT NULL DEFAULT '',
  author_name     TEXT NOT NULL DEFAULT '',
  author_id       TEXT NOT NULL DEFAULT '',
  cover_url       TEXT NOT NULL DEFAULT '',
  duration_sec    INTEGER,                    -- 抖音搜索页可能没有
  play_count      INTEGER,                    -- 抖音搜索页可能是点赞数
  like_count      INTEGER,
  published_at    TEXT,
  raw_json        TEXT NOT NULL DEFAULT '{}', -- 抓到的原始 card 数据
  excluded        INTEGER NOT NULL DEFAULT 0, -- 用户手动剔除（soft delete，仍占 UNIQUE 防再次抓回）
  first_seen_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(platform, platform_video_id)
);
CREATE INDEX idx_videos_platform ON videos(platform);
CREATE INDEX idx_videos_first_seen ON videos(first_seen_at DESC);

-- 多对多：视频 ↔ 关键词命中
CREATE TABLE video_source_keywords (
  video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  keyword         TEXT NOT NULL,
  job_id          INTEGER NOT NULL REFERENCES mining_jobs(id) ON DELETE CASCADE,
  rank_in_search  INTEGER NOT NULL,           -- 1-based 位次
  found_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (video_id, keyword, job_id)
);
CREATE INDEX idx_vsk_keyword ON video_source_keywords(keyword);
CREATE INDEX idx_vsk_job ON video_source_keywords(job_id);
```

**设计说明：**

1. **去重锚点 `(platform, platform_video_id)`** —— URL 形态会变（短链/modal_id），平台内部 ID 稳定。Douyin 现有 `_VIDEO_ID_PATTERNS` 已在做类似提取。
2. **`raw_json` 保留原始 card 数据** —— MVP 不进详情页，但后续 AI 总结 / enrich 不必回平台重抓。
3. **`excluded` soft delete** —— 用户主动剔除的视频不真删，避免下一轮抓取又被插回。
4. **`video_source_keywords` 三元主键 `(video_id, keyword, job_id)`** —— 同一视频被同一关键词在两次 job 中命中是两行，能看到历史命中曲线。

---

## 5. 抓取流程

### 5.1 适配器 Protocol

```python
# csm_core/mining/platforms/_common.py
from dataclasses import dataclass, field
from typing import Callable, Protocol, Literal
import threading

@dataclass
class VideoCard:
    platform: str
    platform_video_id: str
    url: str
    title: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_url: str = ""
    duration_sec: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    published_at: str | None = None
    raw: dict = field(default_factory=dict)
    rank_in_search: int = 0  # 1-based

@dataclass
class ProgressUpdate:
    platform: str
    phase: Literal["launching", "logging_in", "scrolling", "done", "failed", "needs_login", "risk_control"]
    got: int
    target: int
    note: str = ""

@dataclass
class SearchOutcome:
    platform: str
    status: Literal["done", "failed", "needs_login", "risk_control", "cancelled"]
    cards_emitted: int
    error_message: str = ""

class SearchAdapter(Protocol):
    platform: str
    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: Callable[[VideoCard], None],
        on_progress: Callable[[ProgressUpdate], None],
        cancel_event: threading.Event,
    ) -> SearchOutcome: ...
```

### 5.2 三平台执行策略

| 平台 | URL 模板 | 方式 | 反爬关键点 |
|---|---|---|---|
| B 站 | `https://search.bilibili.com/all?keyword=…` | patchright 有头浏览器 + 持久化 profile，滚动加载或翻页 | wbi 签名加强；profile 持久化以维持 session |
| 快手 | `https://www.kuaishou.com/search/video?searchKey=…` | patchright 有头 + 持久化 profile，滚动加载 | 滑块验证码偶发 |
| 抖音 | `https://www.douyin.com/search/{keyword}?type=video` | patchright 有头 + 持久化 profile，滚动加载 | X-Bogus + 强制登录 + 频繁滑块；MVP 接受 needs_login fallback |

**所有平台采用同一种执行手法**：patchright 启动一个有头 Chromium，user-data-dir 独立到 `<config_dir>/browser_profiles/{platform}/`，导航到搜索 URL，等候列表渲染，滚动加载，从 DOM 或拦截到的 XHR/JSON 中提取卡片字段。具体选择 DOM 还是 XHR 由各平台 adapter 内部决定（B 站偏向 XHR，抖音偏向 DOM）。

### 5.3 Runner 执行模型

```
[POST /api/mining/jobs] 
   ↓ 在 mining_jobs 插一行 status=pending，返回 job_id
   ↓
mining_service.submit_job(job_id) 投递到 ThreadPoolExecutor(max_workers=1)
   ↓
MiningRunner.run(job_id):
   storage.mark_started(job_id)
   event_bus.emit("mining.job.started", {job_id})
   for platform in job.platforms:           # 串行
       if cancel_event.is_set(): break
       adapter = get_adapter(platform)
       outcome = adapter.search(
           keyword=job.keyword,
           target_count=job.target_per_platform,
           on_card=lambda card, p=platform: _on_card(job_id, p, card),
           on_progress=lambda pu, p=platform: _on_progress(job_id, p, pu),
           cancel_event=cancel_event,
       )
       storage.update_platform_progress(job_id, platform, outcome)
       event_bus.emit("mining.job.platform_done", {job_id, platform, outcome})
   final = storage.finalize_job(job_id)     # 算 done/partial_done/failed
   event_bus.emit("mining.job.finished", {job_id, summary: final})

def _on_card(job_id, platform, card):
    storage.upsert_video_and_link(card, job_id, platform)  # INSERT OR IGNORE + 总是 link source_keyword

def _on_progress(job_id, platform, pu):
    storage.update_progress_json(job_id, platform, pu)
    # 节流：每抓 5 条或每 10 秒发一次事件
    if _should_emit(...):
        event_bus.emit("mining.job.progress", {job_id, platform, pu})
```

**关键设计点：**

1. **三平台串行** —— patchright 一个实例 300-500MB，串行避免内存爆。`ThreadPoolExecutor(max_workers=1)` 也意味着**全局只允许一个 mining job 同时跑**；二次提交直接拒绝并提示。
2. **流式 upsert** —— `on_card` 立刻落库。中途被风控/取消，已抓数据保住。
3. **进度事件节流** —— SSE 不能每条卡都推；按"每抓 5 条或每 10 秒"取一次最新进度发出。
4. **平台间互不阻塞** —— 抖音 fail/needs_login 不影响 B 站快手继续跑。最终 `status` 由三平台子状态聚合（全 done → done；混合 → partial_done；全失败 → failed）。
5. **熔断 + 限速** —— `from csm_core.browser_infra.rate_limit import get_pacer, get_breaker`，与 monitor 共享熔断状态。

---

## 6. Sidecar API

```
POST   /api/mining/jobs               body: {keyword: str, platforms?: [str], target_per_platform?: int}
                                      → {job_id, status: "pending"}
GET    /api/mining/jobs?limit=20      最近 N 个 job
GET    /api/mining/jobs/{id}          单个 job 详情（含 progress_json）
POST   /api/mining/jobs/{id}/cancel   设置 cancel_event

GET    /api/mining/jobs/{id}/videos   该 job 抓到的视频（含 rank）
GET    /api/mining/videos             全局视频库分页查询
       query: ?keyword=&platform=&since=&until=&q=&offset=&limit=
DELETE /api/mining/videos/{id}        soft delete（excluded=1）
GET    /api/mining/videos/export.csv  导出 CSV（同 query 过滤）

POST   /api/mining/login/{platform}           启动该平台首次登录浏览器
                                              → {browser_session_id}
POST   /api/mining/login/{platform}/confirm   用户登好后点确认；sidecar 读取 cookie 落到 profile
GET    /api/mining/login/status               三平台 profile 是否有有效 cookie
```

**事件（经现有 `event_bus`，前端通过 SSE 接收）：**

- `mining.job.started` `{job_id, keyword}`
- `mining.job.progress` `{job_id, platform, phase, got, target}`
- `mining.job.platform_done` `{job_id, platform, status, count}`
- `mining.job.finished` `{job_id, summary: {total, per_platform}}`
- `mining.login.required` `{platform, job_id?}`

---

## 7. 前端 UX

`MiningView.vue` 三区段：顶部操作栏 → 进行中任务卡 → 视频库表。

### 7.1 顶部操作栏
- `[+ 新任务]`：弹 `StartJobModal`（keyword 输入框 + 三平台勾选 + target 滑条，默认 50，上限 200）。提交后立刻关弹窗，进度卡出现。
- `[⚙ 平台登录]`：弹 `PlatformLoginPanel`，三平台各一行「已登录 / 需要登录」+「登录 / 重新登录」按钮。点击调 `POST /api/mining/login/{platform}`，sidecar 启动有头 patchright，用户登录后点"我登好了"。
- `[⏬ 导出 CSV]`：按当前筛选导出。

### 7.2 进行中任务卡（`JobProgressCard.vue`）
- 显示 keyword、整体状态、三平台 progress bar（`got / target` + phase 文案）、`[取消]` 按钮。
- 通过 SSE `mining.*` 事件实时刷新。
- 收到 `mining.login.required` 时该平台行变红并出 `[去登录]` 按钮，点击直跳 `PlatformLoginPanel`。

### 7.3 视频库表（`VideoTable.vue`）
- 筛选区：关键词下拉、平台下拉、时间范围、全文搜索。
- 每行：封面缩略图、标题、平台徽章、作者、播放/点赞、命中关键词 chips、时长。
- 行操作：`[写评论计划]`（MVP 灰色禁用，tooltip："第二期上线"——预埋 UI hook）、`[打开]`（用系统浏览器打开 URL）、`[剔除]`（调 DELETE，soft delete）。
- 虚拟滚动，分页拉取。

### 7.4 Pinia store（`stores/mining.ts`）
- 状态：`activeJobs: MiningJob[]`、`videos: PaginatedList`、`loginStatus: Record<platform, bool>`、`filters: {keyword, platform, ...}`。
- 监听 SSE `mining.*` 增量更新 `activeJobs`。

---

## 8. 错误处理 / 风控 / 中断

| 场景 | 处理 |
|---|---|
| 平台 cookie 失效 / 无有效 profile | adapter 启动检测，发 `mining.login.required` → 该平台 `phase=needs_login` 跳过；其余平台继续 |
| 滑块/验证码 | adapter 命中典型 DOM/URL 特征抛 `RiskControl`；状态 `risk_control`，记 error 信息 |
| patchright 启动失败 | job `error_message` 写入异常，整体 `failed` |
| 用户点取消 | runner 持 `cancel_event`，每滚一页或每 N 条 check；已抓数据保留 |
| Sidecar 崩溃重启 | 启动时把所有 `running` job 标 `interrupted`（不自动恢复——cookie 状态不可知） |
| 同关键词重复起任务 | 前端弹"该关键词 24h 内跑过，确认再跑？"；不阻止重复 |
| 并发起多个 job | ThreadPoolExecutor max_workers=1 + 前端按钮在有 running job 时禁用 |

---

## 9. 测试策略

**单测（`sidecar/tests/`）：**
- `test_mining_storage.py` —— schema migration v2→v3、`upsert_video_and_link` 幂等性、source_keywords 多对一插入。
- `test_mining_routes.py` —— API 输入校验、job 状态机、cancel 行为。
- `test_mining_extract_douyin.py` / `_bilibili.py` / `_kuaishou.py` —— 用离线 HTML/JSON fixture 测字段提取（不打真平台）。
- `test_browser_infra_relocation.py` —— 验证 monitor 包内 re-export 薄层正常工作。

**Fixture：**
- `sidecar/tests/fixtures/mining/{platform}/search_<keyword>.{html,json}` —— 真实抓回的一份样本，脱敏后入库。

**CI 中不跑真实抓取**（flaky + cookie 缺失）。

**手测清单：**
1. 三平台首次登录流程各跑一次。
2. 关键词"扫地机器人"跑全流程，三平台共 ≥100 条。
3. 同关键词二次起任务，无重复 `videos` 行，新增 `video_source_keywords` 行。
4. 跑到一半点取消，已抓数据保留。
5. 抖音 profile 删掉，确认 `mining.login.required` 触发、其余平台继续。
6. 视频库筛选 + 导出 CSV 字段完整。

---

## 10. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| 抖音 X-Bogus / 滑块绕不过 | 抖音平台基本不可用 | 接受 `needs_login` / `risk_control` fallback，B 站 + 快手先跑起来；二期再投入抖音深度对抗 |
| `browser_infra` 提取破坏 monitor | monitor 评论留存功能回归 | re-export 薄层 + `test_browser_infra_relocation.py` 守门；不动 monitor 业务代码 |
| 多平台搜索页结构变化 | adapter 频繁挂 | 字段提取走"DOM + XHR 双通道"；离线 fixture 测试快速复现 |
| 用户主机内存不足（patchright 300MB+ 一个实例） | 跑不动 | 三平台串行 + 全局只允许一个 job |
| 持久化 profile 文件夹被用户误删 | 登录态丢 | 文档明示路径；UI 上"重新登录"按钮一键修复 |
| SQLite WAL 文件膨胀（高频小写入） | 磁盘占用 | 进度事件节流，writes 也节流（每 5 条 commit 一次） |

---

## 11. 后续期 hook 预留

| 后续 | 预埋点 |
|---|---|
| 视频内容 AI 总结 | `videos.raw_json` 保留原始 card；ai_summary 独立表关联 `video_id` |
| 评论计划库 | `videos` 行的"写评论计划"按钮已占位；评论计划独立表 + `video_id` 外键 |
| 监控同步 | 视频投放评论后，由评论计划模块在 `monitor_tasks` 注入 `*_comment` 类型任务 |
| 外派对接 | 评论计划行的"派给机构"按钮；外派状态字段独立 |

---

## 12. 实施顺序提示（给 writing-plans 用）

建议拆成 4 个 commit：

1. **重构**：`browser_infra` 抽取 + monitor re-export 薄层 + `test_browser_infra_relocation.py`
2. **数据层**：mining 三表 migration + `mining/storage.py` + `mining/models.py` + storage 单测
3. **后端核心**：三平台 adapter（先 B 站，再快手，再抖音）+ `mining/runner.py` + sidecar `routes/mining.py` + `services/mining_service.py` + 离线 fixture 单测
4. **前端**：`MiningView` + `StartJobModal` + `JobProgressCard` + `VideoTable` + `PlatformLoginPanel` + `stores/mining.ts`

每步可独立 PR，前后无强阻塞。
