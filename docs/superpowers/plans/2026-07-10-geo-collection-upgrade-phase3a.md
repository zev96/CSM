# GEO 采集升级 Phase 3a —— 诊断链路 + 跳过安全 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 GEO 卡片显示**真实失败原因**(替掉写死的「够不到平台」),并让 RPA 平台在**首格未登录 / 连续失败**时短路跳过、为剩余关键词补**合成 cell**——失败看得懂、被跳平台不缺席、不再白等。

**Architecture:** 后端新增有限枚举 `fail_reason` 的纯函数分类器(吃 error 文本 + status,输出 9 类),`GeoCell` 加 `fail_reason` 字段,v10 迁移加 `geo_cells.fail_reason` 列;所有 error/blocked cell 构造处回填分类结果;`_rpa_batch` 从 fetch 内嵌函数提升为方法并加「登录 gate + 连败短路」,跳过时对剩余关键词 `yield` 合成 blocked cell(携带触发失败的 fail_reason);前端 `RawCell`/`PlatformVM`/`cellToPlatform` 增读 `fail_reason` + `failReasonLabel` 映射,替换 `GeoPlatformStrip` / `GeoPlatformBlock` 的写死文案。全部增量、向后兼容(旧库/旧 cell 缺列走默认 `""`)。

**Tech Stack:** Python 3.12(pydantic v2 / sqlite3 / pytest)+ Vue 3 / TypeScript(vitest / vue-tsc)。

---

## 背景锚点(已核实的当前代码事实,写代码前必读)

- `GeoCell`(`csm_core/monitor/geo/models.py:53`)**无** `fail_reason` 字段;`AnswerStatus = Literal["ok","empty","blocked","error"]`(不改)。
- error/blocked cell 的构造点共 **6 处**,全在 `csm_core/monitor/platforms/geo_query.py`:
  - `_run_cell`:answer 非 ok 分支(`:209`)、异常分支(`:224`)。
  - `_run_cell_on_session`:answer 非 ok 分支(`:231`)、异常分支(`:243`)。
  - `_rpa_batch`(**当前是 fetch 内嵌函数**,`:106`):provider 构造失败(`:115`)、session 中断(`:130`)。
- RPA 未登录来源:`_driver.run_one_keyword`(`providers/rpa/_driver.py:22`)返回 `GeoAnswer(status="blocked", error=spec.login_blocked_msg)`;`login_blocked_msg` 含「未登录」(见 `sites.py`,三站均是「X 未登录,请在设置中…登录」)。
- DB 迁移:`csm_core/monitor/storage.py` —— `_SCHEMA_VERSION = 9`(`:27`),`_migrate`(`:129`)按 v1→v9 链式调各 `apply_vN`(全幂等,每次 init 都重跑),`_ensure_column`(`:162`)幂等加列。geo 表迁移是 `apply_v7_migration`(`geo/storage.py:59`,已用 `_ensure_column` 补过 `extraction_json`)。**geo_storage 在 `_migrate` 内已 import(`:147`)**。
- 存储:`record_run`(`geo/storage.py:89`)单事务写 cells;`_hydrate_cells`(`:207`)用 `**dict(r)` + `SELECT *`,**新列自动流到前端**;`cells_for_latest_run`(`:258`)供 `latest-cells` 路由。
- 路由:`/api/monitor/geo/{task_id}/latest-cells`(`sidecar/csm_sidecar/routes/monitor.py:788`)只 `return {"cells": cells_for_latest_run(task_id)}` —— `SELECT *` 直传,**本计划不动路由**。
- KPI 安全:`metrics._block`(`geo/metrics.py:27`)分母 `ok_total = status=="ok"`,合成 **blocked** cell 记入 `error_cells`、不进 SoC/首推率分母、`mentioned=False`——**合成 cell 不污染任何 KPI**,无需改 metrics。
- 告警安全:`alerts.py` 的 `platform_dropped` 有 `ok_total>0` 守卫,合成 blocked cell 不触发假「跌出 Top-N」(spec §4.5 已核实)。
- runner 契约:`runner._rpa_worker`(`geo/runner.py:79`)要求 `rpa_batch` 对每平台**恰好 yield `len(plat_keywords)` 个 `(local_idx, cell)`**,否则抛「漏产」(`:111`)。合成 cell 正好补足这个契约。
- 前端失败文案 **3 处**:`GeoPlatformStrip.vue:68`(L1 各平台卡位条,截图那张卡,写死「够不到平台」)、`GeoPlatformBlock.vue:118`(L2 明细「本平台本次采集失败」)、`geoDetail.ts:221` `cellStatus` 徽章 label「采集失败」。`isFailed`(`geoDetail.ts:200`)= `status∈{error,blocked}` —— **语义不改**,只做增量文案。
- 前端测试风格:`__tests__/geoDetail.spec.ts` 用 vitest + `vm(id, opts)` 工厂(`opts: Partial<PlatformVM>`,加可选字段无需改工厂),从 `@/components/monitor/geo/geoDetail` import 纯函数。

## 如何跑测试(worktree;主仓 checkout 在别的分支,必须覆盖 PYTHONPATH)

**Python(PowerShell,主 shell):**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\objective-moore-ecce71;D:\CSM\.claude\worktrees\objective-moore-ecce71\sidecar"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest tests/core/monitor/geo/ -q
```

单文件:把 `tests/core/monitor/geo/` 换成具体文件(如 `tests/core/monitor/geo/test_fail_reason.py`)。

**前端(在 `frontend/` 目录):**

```powershell
npx vitest run src/components/monitor/geo/__tests__/geoDetail.spec.ts
npx vue-tsc --noEmit -p tsconfig.app.json   # 类型检查;用 --noEmit,勿用 -b(会 emit vite.config.js 触发 vite 重启)
```

> ⚠ `sidecar/tests/` 不在默认 pytest / CI 里(`testpaths=["tests"]`)。本计划不碰 sidecar 逻辑,但 Task 7 回归要**显式**加跑 `pytest sidecar/tests/ -q` 确认没连带打断。

---

## File Structure

| 文件 | 责任 | 本计划改动 |
|---|---|---|
| `csm_core/monitor/geo/fail_reason.py` | **新建**。`FailReason` 枚举 + 纯函数 `classify_fail_reason(status, error)` | Task 1 |
| `csm_core/monitor/geo/models.py` | GeoCell 数据模型 | Task 1:加 `fail_reason` 字段 |
| `csm_core/monitor/geo/storage.py` | geo_cells DDL + record_run + v7 迁移 | Task 2:CREATE 加列 + `apply_v10_migration` + INSERT 写 fail_reason |
| `csm_core/monitor/storage.py` | 迁移 runner + schema 版本 | Task 2:`_SCHEMA_VERSION=10` + 调 `apply_v10_migration` |
| `csm_core/monitor/platforms/geo_query.py` | fetch 编排 + cell 构造 | Task 3:6 处回填 fail_reason;Task 4:`_rpa_batch` 提为方法 + gate/短路/合成 cell |
| `frontend/src/components/monitor/geo/geoDetail.ts` | cell→VM 数据层 + 纯 helper | Task 5:`RawCell.fail_reason` + `PlatformVM.failReason` + `cellToPlatform` 映射 + `failReasonLabel` |
| `frontend/src/components/monitor/geo/GeoPlatformStrip.vue` | L1 各平台卡位条 | Task 6:副标题用 `failReasonLabel` |
| `frontend/src/components/monitor/geo/GeoPlatformBlock.vue` | L2 平台明细块 | Task 6:失败正文用 `failReasonLabel` |
| `tests/core/monitor/geo/test_fail_reason.py` | **新建** | Task 1 |
| `tests/core/monitor/geo/test_storage.py` | geo 存储测试 | Task 2:加 fail_reason round-trip |
| `tests/core/monitor/geo/test_geo_query_adapter.py` | adapter 测试 | Task 3/4:回填 + gate/短路 |
| `frontend/src/components/monitor/geo/__tests__/geoDetail.spec.ts` | 前端纯函数测试 | Task 5:`failReasonLabel` + `cellToPlatform` |

---

## Task 1: `fail_reason` 分类器 + GeoCell 字段

**Files:**
- Create: `csm_core/monitor/geo/fail_reason.py`
- Modify: `csm_core/monitor/geo/models.py:53-64`(GeoCell 加字段)
- Test: `tests/core/monitor/geo/test_fail_reason.py`(新建)

- [ ] **Step 1: 写失败测试**

`tests/core/monitor/geo/test_fail_reason.py`:

```python
from __future__ import annotations
import pytest

from csm_core.monitor.geo.fail_reason import classify_fail_reason
from csm_core.monitor.geo.models import GeoCell


@pytest.mark.parametrize("status,error,expected", [
    # 未登录:RPA blocked 走 login_blocked_msg(含「未登录」);API 401/unauthorized
    ("blocked", "Kimi 未登录，请在设置中登录", "not_logged_in"),
    ("blocked", "腾讯元宝 未登录，请在设置中扫码登录", "not_logged_in"),
    ("error", "HTTP 401 unauthorized", "not_logged_in"),
    # 限流
    ("error", "HTTP 429 Too Many Requests", "rate_limited"),
    ("error", "触发限流，请稍后重试", "rate_limited"),
    # 配额/欠费
    ("error", "account balance insufficient", "quota_exhausted"),
    ("error", "账户欠费，请充值", "quota_exhausted"),
    # 内容风控
    ("error", "内容触发风控，已拦截", "content_blocked"),
    # 流式超时:wait_stream_done 专属标记,必须早于泛 timeout
    ("error", "TimeoutError: wait_stream_done exceeded 120s", "timeout"),
    # 选择器漂移:Playwright 点击/等待元素超时、找不到元素
    ("error", "Page.click: Timeout 30000ms exceeded. waiting for selector \"button.send\"", "selector_drift"),
    ("error", "locator not found: div.ql-editor", "selector_drift"),
    # 网络/浏览器传输
    ("error", "Target page, context or browser has been closed", "network"),
    ("error", "httpx.ConnectError: connection refused", "network"),
    # 兜底:blocked 但文案未命中 → not_logged_in(最可行动);error → unknown
    ("blocked", "看不懂的中断信息", "not_logged_in"),
    ("error", "看不懂的中断信息", "unknown"),
])
def test_classify_fail_reason(status, error, expected):
    assert classify_fail_reason(status=status, error=error) == expected


def test_stream_timeout_beats_selector_timeout():
    # 两者都含 "timeout";含 wait_stream_done 的必须归 timeout 不是 selector_drift
    assert classify_fail_reason(
        status="error", error="wait_stream_done exceeded 180s (Timeout)") == "timeout"


def test_geocell_has_fail_reason_field_default_empty():
    c = GeoCell(platform="kimi", keyword="k1")
    assert c.fail_reason == ""
    c2 = GeoCell(platform="kimi", keyword="k1", status="error", fail_reason="timeout")
    assert c2.fail_reason == "timeout"
```

- [ ] **Step 2: 跑测试确认失败**

Run(见顶部命令):`pytest tests/core/monitor/geo/test_fail_reason.py -q`
Expected: FAIL —— `ModuleNotFoundError: csm_core.monitor.geo.fail_reason` + GeoCell 无 `fail_reason`。

- [ ] **Step 3: 实现分类器**

Create `csm_core/monitor/geo/fail_reason.py`:

```python
"""失败原因分类(纯函数)—— 把 provider 的 error 文本 + status 归一到有限枚举,
供前端映射成人话(替掉写死的「够不到平台」)。

只吃字符串(error = 落库的 repr(e) / blocked 文案)+ status,不吃异常对象:
error cell 存库存的是 repr,下钻/前端拿到的也是字符串,单一真相源。

优先级(从最具体到最泛,首个命中即返回)——顺序是正确性的一部分:
  中断 > 未登录 > 限流 > 配额 > 风控 > 流超时 > 选择器 > 网络 > 兜底。
「流超时」(wait_stream_done 专属标记)必须早于泛化的 "timeout",因为
Playwright 的选择器/点击超时消息也含 "timeout",否则会把流超时误判成选择器漂移。
"""
from __future__ import annotations
from typing import Literal

FailReason = Literal[
    "not_logged_in", "timeout", "selector_drift", "rate_limited",
    "quota_exhausted", "content_blocked", "network", "interrupted", "unknown",
]


def classify_fail_reason(*, status: str, error: str) -> str:
    """把 (status, error 文本) 归类成 FailReason 之一。纯函数,无 I/O。"""
    e = error or ""
    t = e.lower()
    # 1) 中断(睡眠唤醒 / wall-clock 跳变)—— Phase 3b 会在 error 里打这些标记;
    #    3a 先把映射备好,3b 接上检测即生效。
    if "interrupted" in t or "时钟跳变" in e or "睡眠唤醒" in e:
        return "interrupted"
    # 2) 未登录 —— RPA blocked 的 login_blocked_msg 含「未登录」;API 侧 401/未授权。
    if ("未登录" in e or "请登录" in e or "登录已过期" in e
            or "not logged" in t or "unauthorized" in t or "401" in t):
        return "not_logged_in"
    # 3) 限流。
    if ("429" in t or "rate limit" in t or "too many requests" in t
            or "限流" in e or "频繁" in e):
        return "rate_limited"
    # 4) 配额 / 欠费。
    if ("quota" in t or "insufficient" in t or "balance" in t or "arrears" in t
            or "欠费" in e or "余额" in e or "配额" in e):
        return "quota_exhausted"
    # 5) 内容风控。
    if ("风控" in e or "敏感" in e or "违规" in e or "content_filter" in t
            or ("content" in t and "block" in t)):
        return "content_blocked"
    # 6) 流式超时(答案没在期限内收敛)—— 必须早于泛 timeout(见模块头注)。
    if "wait_stream_done" in t or ("stream" in t and "timeout" in t):
        return "timeout"
    # 7) 选择器漂移(Playwright 点击 / 等待元素超时、找不到元素)。
    if ("timeout" in t or "waiting for" in t or "selector" in t or "locator" in t
            or "找不到" in e or "no element" in t or "not found" in t):
        return "selector_drift"
    # 8) 网络 / 浏览器传输异常(连接、页面被关)。
    if (("target" in t and "closed" in t) or "connect" in t or "connection" in t
            or "network" in t or "ssl" in t or "econn" in t):
        return "network"
    # 9) 兜底:blocked 未命中上面任一 → 多半仍是登录/风控,给 not_logged_in
    #    (用户第一反应去登录,比 unknown 更可行动);error → unknown。
    if status == "blocked":
        return "not_logged_in"
    return "unknown"
```

Modify `csm_core/monitor/geo/models.py` —— GeoCell 加 `fail_reason` 字段(在 `status` 之后):

```python
class GeoCell(BaseModel):
    platform: str
    keyword: str
    mentioned: bool = False
    rank: int = -1
    sentiment: Sentiment = "na"
    answer_text: str = ""
    status: AnswerStatus = "ok"   # ok/empty/blocked/error，与 GeoAnswer 同值域
    fail_reason: str = ""         # 失败原因分类(见 geo.fail_reason;ok cell 恒 ""）
    raw: dict[str, Any] = Field(default_factory=dict)
    citations: list[ClassifiedCitation] = Field(default_factory=list)
    recommended: list[RecommendedEntity] = Field(default_factory=list)
    summary: str = ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_fail_reason.py -q`
Expected: PASS(18 参数化 + 2 用例全绿）。

- [ ] **Step 5: 提交**

```powershell
git add csm_core/monitor/geo/fail_reason.py csm_core/monitor/geo/models.py tests/core/monitor/geo/test_fail_reason.py
git commit -m "feat(geo): fail_reason 分类器 + GeoCell.fail_reason 字段(Phase 3a T1)"
```

---

## Task 2: v10 迁移 —— `geo_cells.fail_reason` 列 + record_run 写入

**Files:**
- Modify: `csm_core/monitor/geo/storage.py:22-56`(CREATE 加列)、`:59-69`(加 `apply_v10_migration`)、`:104-114`(INSERT 写 fail_reason)
- Modify: `csm_core/monitor/storage.py:27`(`_SCHEMA_VERSION=10`)、`:156`(调 `apply_v10_migration`)
- Test: `tests/core/monitor/geo/test_storage.py`

- [ ] **Step 1: 写失败测试**

在 `tests/core/monitor/geo/test_storage.py` 末尾追加(该文件已有 `init_db` fixture 与 record_run 用法,沿用其既有 fixture;若测试用独立临时库,照抄本测试内联的 init):

```python
def test_record_run_persists_fail_reason(tmp_path):
    # 独立临时库,避免与其他测试共享连接串。
    import csm_core.monitor.storage as ms
    from csm_core.monitor.geo import storage as gs
    from csm_core.monitor.geo.models import GeoCell
    ms._initialized = False
    ms._db_path = None
    ms.init_db(str(tmp_path / "m.db"))

    from datetime import datetime
    ts = datetime.utcnow()
    cells = [
        GeoCell(platform="kimi", keyword="k1", status="ok"),  # ok → fail_reason 恒 ""
        GeoCell(platform="deepseek", keyword="k1", status="blocked",
                fail_reason="not_logged_in", raw={"error": "DeepSeek 未登录"}),
        GeoCell(platform="tongyi", keyword="k1", status="error",
                fail_reason="timeout", raw={"error": "wait_stream_done exceeded"}),
    ]
    gs.record_run(1, ts, cells)

    rows = gs.cells_for_run(1, ts)
    by_plat = {r["platform"]: r for r in rows}
    assert by_plat["kimi"]["fail_reason"] == ""
    assert by_plat["deepseek"]["fail_reason"] == "not_logged_in"
    assert by_plat["tongyi"]["fail_reason"] == "timeout"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_storage.py::test_record_run_persists_fail_reason -q`
Expected: FAIL —— `KeyError: 'fail_reason'`(列不存在 / INSERT 未写)。

- [ ] **Step 3: 实现迁移 + 写入**

`csm_core/monitor/geo/storage.py` —— CREATE TABLE 加列(`_DDL_V7_GEO` 首条,在 `status` 后):

```python
        status      TEXT NOT NULL DEFAULT 'ok',
        fail_reason TEXT NOT NULL DEFAULT '',
        raw_json    TEXT NOT NULL DEFAULT '{}',
```

同文件 —— 在 `apply_v7_migration` 之后新增 `apply_v10_migration`:

```python
def apply_v10_migration(conn: sqlite3.Connection) -> None:
    """v9 -> v10: geo_cells.fail_reason —— 失败原因分类列(前端映射人话,替掉写死
    「够不到平台」)。旧库(v7 表已建但无此列)靠 _ensure_column 幂等补上;新库 CREATE
    已含此列,_ensure_column 探到即跳过。Idempotent。"""
    monitor_storage._ensure_column(
        conn, "geo_cells", "fail_reason", "TEXT NOT NULL DEFAULT ''"
    )
```

同文件 —— `record_run` 的 INSERT 加 `fail_reason` 列 + 值 + 占位符(在 `status` 后):

```python
            cur = conn.execute(
                """INSERT INTO geo_cells(task_id, checked_at, platform, keyword,
                       mentioned, rank, sentiment, answer_text, status, fail_reason,
                       raw_json, extraction_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (task_id, ts, c.platform, c.keyword,
                 1 if c.mentioned else 0, c.rank, c.sentiment,
                 c.answer_text, c.status, c.fail_reason,
                 json.dumps(c.raw, ensure_ascii=False),
                 json.dumps({"recommended": [r.model_dump() for r in c.recommended],
                             "summary": c.summary}, ensure_ascii=False)),
            )
```

`csm_core/monitor/storage.py` —— `_SCHEMA_VERSION` 升到 10:

```python
_SCHEMA_VERSION = 10
```

同文件 —— `_migrate` 在 v9(feedback)之后调 v10(此处 `geo_storage` 已于 v7 段 import,在同一函数作用域内可直接用):

```python
    from csm_core.feedback import storage as feedback_storage
    feedback_storage.apply_v9_migration(conn)
    # v10: geo_cells.fail_reason —— 失败原因分类列(前端替掉写死「够不到平台」)。
    # geo_storage 已在 v7 段 import(同一函数作用域)。幂等。
    geo_storage.apply_v10_migration(conn)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
        (str(_SCHEMA_VERSION),),
    )
```

- [ ] **Step 4: 跑测试确认通过 + geo 存储回归**

Run:
```powershell
pytest tests/core/monitor/geo/test_storage.py -q
```
Expected: PASS(新测试 + 既有 record_run/leaderboard/exposure_window 全绿 —— 加列 default `''` 向后兼容,既有断言不变)。

- [ ] **Step 5: 提交**

```powershell
git add csm_core/monitor/geo/storage.py csm_core/monitor/storage.py tests/core/monitor/geo/test_storage.py
git commit -m "feat(geo): v10 迁移 geo_cells.fail_reason + record_run 写入(Phase 3a T2)"
```

---

## Task 3: 回填 fail_reason 到所有 error/blocked cell 构造处

**Files:**
- Modify: `csm_core/monitor/platforms/geo_query.py`(import + `_run_cell` 2 处 + `_run_cell_on_session` 2 处;`_rpa_batch` 的 2 处放到 Task 4 一起改)
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py`

> 说明:本任务只回填 `_run_cell` / `_run_cell_on_session`(非 batch 路径,API 车道 + 单发)。`_rpa_batch` 的 2 处回填与 gate/短路 一起在 Task 4 落,避免同一函数被改两次。

- [ ] **Step 1: 写失败测试**

在 `tests/core/monitor/geo/test_geo_query_adapter.py` 追加(用直接调方法 + monkeypatch `get_provider` 的方式,避开整个 fetch 机器):

```python
def test_run_cell_populates_fail_reason(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    from csm_core.monitor.geo.models import GeoAnswer

    adapter = gq.GeoQueryAdapter()

    # blocked(未登录)→ fail_reason=not_logged_in
    class _Blocked:
        mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            return GeoAnswer(platform="deepseek", keyword=kw, status="blocked",
                             error="DeepSeek 未登录，请在设置中登录")
    monkeypatch.setattr(gq, "get_provider", lambda p: _Blocked())
    cell = adapter._run_cell("k1", "deepseek", "云野", [], True, client=object())
    assert cell.status == "blocked"
    assert cell.fail_reason == "not_logged_in"

    # 异常(流超时)→ status=error, fail_reason=timeout
    class _Timeout:
        mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            raise TimeoutError("wait_stream_done exceeded 180s")
    monkeypatch.setattr(gq, "get_provider", lambda p: _Timeout())
    cell = adapter._run_cell("k1", "kimi", "云野", [], True, client=object())
    assert cell.status == "error"
    assert cell.fail_reason == "timeout"


def test_run_cell_on_session_populates_fail_reason():
    from csm_core.monitor.platforms import geo_query as gq
    from csm_core.monitor.geo.models import GeoAnswer

    adapter = gq.GeoQueryAdapter()

    def query_one(kw):   # 直接给 session 上的 query_one
        return GeoAnswer(platform="yuanbao", keyword=kw, status="blocked",
                         error="腾讯元宝 未登录，请在设置中扫码登录")
    cell = adapter._run_cell_on_session(query_one, "k1", "yuanbao", "云野", [], client=object())
    assert cell.status == "blocked"
    assert cell.fail_reason == "not_logged_in"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_geo_query_adapter.py::test_run_cell_populates_fail_reason tests/core/monitor/geo/test_geo_query_adapter.py::test_run_cell_on_session_populates_fail_reason -q`
Expected: FAIL —— `cell.fail_reason == ""`(未回填)。

- [ ] **Step 3: 实现回填**

`csm_core/monitor/platforms/geo_query.py` —— 顶部 import 段加(在 `from ..geo import metrics` 附近):

```python
from ..geo.fail_reason import classify_fail_reason
```

`_run_cell` —— 两处构造改为带 fail_reason:

```python
            answer = provider.query(keyword, web_search=web_search, cancel_token=cancel_token)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="",
                               fail_reason=classify_fail_reason(status=answer.status, error=answer.error),
                               raw={"error": answer.error})
```

```python
        except Exception as e:                       # cell 级隔离
            if is_cancelled(e):                      # 用户 Stop：上抛给 loop 干净处理
                raise                                # 不记 error cell、不打噪声 traceback
            logger.exception("[geo] cell 失败 kw=%s plat=%s", keyword, platform)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           fail_reason=classify_fail_reason(status="error", error=repr(e)),
                           raw={"error": repr(e)})
```

`_run_cell_on_session` —— 同样两处:

```python
            answer = query_one(keyword)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="",
                               fail_reason=classify_fail_reason(status=answer.status, error=answer.error),
                               raw={"error": answer.error})
```

```python
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo] rpa cell 失败 kw=%s plat=%s", keyword, platform)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           fail_reason=classify_fail_reason(status="error", error=repr(e)),
                           raw={"error": repr(e)})
```

- [ ] **Step 4: 跑测试确认通过 + adapter 回归**

Run:
```powershell
pytest tests/core/monitor/geo/test_geo_query_adapter.py -q
```
Expected: PASS(新 2 测试 + 既有 adapter 测试全绿)。

- [ ] **Step 5: 提交**

```powershell
git add csm_core/monitor/platforms/geo_query.py tests/core/monitor/geo/test_geo_query_adapter.py
git commit -m "feat(geo): _run_cell/_run_cell_on_session 回填 fail_reason(Phase 3a T3)"
```

---

## Task 4: `_rpa_batch` 提为方法 + 登录 gate + 连败短路 + 合成 cell

**Files:**
- Modify: `csm_core/monitor/platforms/geo_query.py`(把 fetch 内嵌 `_rpa_batch` 提为方法 `_rpa_batch`;fetch 内改为 lambda 调用 + 读 `geo_consecutive_fail_skip` 配置)
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py`

**设计(faithful to spec §4.3 + §4.5):**
- **登录 gate**:首关键词(`local_idx==0`)返回 `status=="blocked"` → 平台没登录,余下关键词全出**合成 blocked cell**(不再问),携带该 blocked cell 的 `fail_reason`(通常 `not_logged_in`)。
- **连败短路**:连续 `consec_skip`(默认 3)个关键词 `status∈{error,blocked}` → 余下全出合成 cell,携带**最后一个失败** cell 的 `fail_reason`。
- 合成 cell:`status="blocked"`(§4.5:被跳=没问到,记 error_cells、不进 KPI 分母、不触发假告警),`raw={"error": <原因说明>, "synthetic": True}`。
- **契约**:仍对每个关键词各 yield 一个 `(local_idx, cell)`——合成 cell 正好补足 runner 的「漏产」检查。
- provider 构造失败 / session 中断的隔离(原 `_rpa_batch` 已有)保留并回填 fail_reason。

- [ ] **Step 1: 写失败测试**

在 `tests/core/monitor/geo/test_geo_query_adapter.py` 追加:

```python
def _fake_provider_yielding(script):
    """返回一个 provider,其 session() 的 query_one(kw) 按 script[kw] 出 GeoAnswer。"""
    import contextlib
    from csm_core.monitor.geo.models import GeoAnswer

    class _P:
        mode = "rpa"
        @contextlib.contextmanager
        def session(self, *, web_search, cancel_token=None):
            def query_one(kw):
                st, err = script[kw]
                if st == "ok":
                    return GeoAnswer(platform="kimi", keyword=kw, answer_text="有内容", status="ok")
                return GeoAnswer(platform="kimi", keyword=kw, status=st, error=err)
            yield query_one
    return _P()


def _drain_batch(adapter, plat, kws, provider, monkeypatch, consec_skip=3):
    from csm_core.monitor.platforms import geo_query as gq
    monkeypatch.setattr(gq, "get_provider", lambda p: provider)
    # ok cell 会走 extract → 打桩成恒定 GeoExtraction,避免真调 LLM。
    from csm_core.monitor.geo.models import GeoExtraction
    monkeypatch.setattr(gq, "extract",
                        lambda answer, *, brand, aliases, client: GeoExtraction(mentioned=False))
    out = list(adapter._rpa_batch(plat, kws, None, web_search=True, brand="云野",
                                  aliases=[], client=object(), consec_skip=consec_skip))
    return out


def test_rpa_batch_login_gate_synthesizes_rest(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3"]
    provider = _fake_provider_yielding({
        "k1": ("blocked", "Kimi 未登录，请在设置中登录"),
        "k2": ("ok", ""), "k3": ("ok", ""),   # 不该被调用
    })
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch)
    assert [li for li, _ in out] == [0, 1, 2]              # 契约:每关键词一 cell
    cells = [c for _, c in out]
    assert cells[0].status == "blocked" and cells[0].fail_reason == "not_logged_in"
    # k2/k3 是合成 cell:blocked + 继承 not_logged_in + synthetic 标记
    for c in cells[1:]:
        assert c.status == "blocked"
        assert c.fail_reason == "not_logged_in"
        assert c.raw.get("synthetic") is True


def test_rpa_batch_consecutive_fail_short_circuits(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3", "k4", "k5"]
    # 前 3 个 error(非首格 blocked,不触发 gate),连败达阈值 3 → k4/k5 合成
    provider = _fake_provider_yielding({
        "k1": ("error", "wait_stream_done exceeded"),
        "k2": ("error", "wait_stream_done exceeded"),
        "k3": ("error", "wait_stream_done exceeded"),
        "k4": ("ok", ""), "k5": ("ok", ""),   # 不该被调用
    })
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch, consec_skip=3)
    cells = [c for _, c in out]
    assert len(cells) == 5                                  # 契约:补足 5 个
    assert [c.status for c in cells[:3]] == ["error", "error", "error"]
    assert all(c.fail_reason == "timeout" for c in cells[:3])
    for c in cells[3:]:                                     # k4/k5 合成,继承 timeout
        assert c.status == "blocked"
        assert c.fail_reason == "timeout"
        assert c.raw.get("synthetic") is True


def test_rpa_batch_no_early_skip_when_recovers(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3", "k4"]
    # error,error,ok(连败清零),error → 从不达 3 连败,全部真跑
    provider = _fake_provider_yielding({
        "k1": ("error", "x"), "k2": ("error", "x"),
        "k3": ("ok", ""), "k4": ("error", "x"),
    })
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch, consec_skip=3)
    cells = [c for _, c in out]
    assert [c.raw.get("synthetic") for c in cells] == [None, None, None, None]  # 无合成
    assert [c.status for c in cells] == ["error", "error", "ok", "error"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_geo_query_adapter.py -k rpa_batch -q`
Expected: FAIL —— `_rpa_batch` 还是 fetch 内嵌函数,`adapter._rpa_batch` 不存在(`AttributeError`)。

- [ ] **Step 3: 实现 —— 提为方法 + gate/短路/合成**

`csm_core/monitor/platforms/geo_query.py` —— **删除** fetch 内的内嵌 `_rpa_batch` 定义(`:106-131` 那一段),在 `_run_cell_on_session` 之后**新增方法**:

```python
    def _rpa_batch(self, plat, plat_keywords, tok, *, web_search, brand, aliases,
                   client, consec_skip):
        """每平台开一次 session,循环关键词逐 cell yield(浏览器跨关键词复用)。

        登录 gate(§4.3):首关键词返回 blocked = 平台没登录 → 余下关键词全出合成
        blocked cell(不再问,省 goto/等流)。
        连败短路(§4.3):连续 consec_skip 个关键词 status∈{error,blocked} → 余下
        全出合成 cell,携带最后一个失败的 fail_reason。
        合成 cell(§4.5:被跳平台不缺席)status=blocked、携带触发失败的 fail_reason、
        raw.synthetic=True;记 error_cells、不进 KPI 分母、不触发假「跌出」告警。

        契约:必对每个关键词各 yield 一个 (local_idx, cell);provider 构造 / session
        开启(__enter__)/收尾(__exit__)失败 → 该平台每关键词各出一个 error cell(隔离)。
        """
        def _synthetic(start_li, reason, detail):
            for li in range(start_li, len(plat_keywords)):
                yield li, GeoCell(platform=plat, keyword=plat_keywords[li], status="blocked",
                                  fail_reason=reason, raw={"error": detail, "synthetic": True})

        try:
            provider = get_provider(plat)
            session_cm = provider.session(web_search=web_search, cancel_token=tok)
        except Exception as e:                       # 构造失败:全隔离成 error
            reason = classify_fail_reason(status="error", error=repr(e))
            for li, kw in enumerate(plat_keywords):
                yield li, GeoCell(platform=plat, keyword=kw, status="error",
                                  fail_reason=reason, raw={"error": repr(e)})
            return

        produced = 0
        consec = 0
        try:
            with session_cm as query_one:
                for li, kw in enumerate(plat_keywords):
                    maybe_cancel(tok)
                    cell = self._run_cell_on_session(query_one, kw, plat, brand, aliases, client)
                    produced = li + 1
                    yield li, cell
                    failed = cell.status in ("error", "blocked")
                    # 登录 gate:首关键词就 blocked = 平台没登录,别再问剩下的。
                    if li == 0 and cell.status == "blocked":
                        for li2, syn in _synthetic(li + 1, cell.fail_reason or "not_logged_in",
                                                   f"{plat} 首关键词未登录,跳过剩余关键词"):
                            produced = li2 + 1
                            yield li2, syn
                        return
                    consec = consec + 1 if failed else 0
                    if failed and consec >= consec_skip:
                        for li2, syn in _synthetic(li + 1, cell.fail_reason or "unknown",
                                                   f"{plat} 连续 {consec} 个关键词失败,短路跳过剩余"):
                            produced = li2 + 1
                            yield li2, syn
                        return
        except Exception as e:                       # session __enter__/__exit__ 失败或中途非隔离异常
            if is_cancelled(e):
                raise
            logger.exception("[geo] rpa session 中断 plat=%s", plat)
            reason = classify_fail_reason(status="error", error=repr(e))
            for li in range(produced, len(plat_keywords)):
                yield li, GeoCell(platform=plat, keyword=plat_keywords[li], status="error",
                                  fail_reason=reason, raw={"error": f"session 中断: {e!r}"})
```

同文件 —— fetch 内,在 `rpa_conc = _int_cfg(...)` 附近读连败阈值,并把 runner 调用的 `rpa_batch=` 改为 lambda 委托方法:

```python
        api_pool_size = _int_cfg("geo_api_pool_size", 5, 16)
        rpa_conc = _int_cfg("geo_rpa_platform_concurrency", 3, 8)
        consec_skip = _int_cfg("geo_consecutive_fail_skip", 3, 999)
```

```python
        cells: list[GeoCell] = geo_runner.run_cells_dual_lane(
            tail, _cell,
            mode_of=lambda p: mode_map.get(p, "api"),
            api_pool_size=api_pool_size,
            rpa_platform_concurrency=rpa_conc,
            progress_cb=progress_cb,
            initial_done=resume_from,
            cancel_token=cancel_token,
            rpa_batch=lambda plat, kws, t: self._rpa_batch(
                plat, kws, t, web_search=web_search, brand=brand, aliases=aliases,
                client=client, consec_skip=consec_skip),
        )
```

- [ ] **Step 4: 跑测试确认通过 + 全 geo 回归**

Run:
```powershell
pytest tests/core/monitor/geo/ -q
```
Expected: PASS —— 新 3 个 rpa_batch 测试 + 既有 runner/adapter/storage 全绿。特别确认 `test_geo_runner.py` 的 `rpa_batch` 契约测试(漏产/取消)仍绿(合成 cell 补足契约)。

- [ ] **Step 5: 提交**

```powershell
git add csm_core/monitor/platforms/geo_query.py tests/core/monitor/geo/test_geo_query_adapter.py
git commit -m "feat(geo): _rpa_batch 提为方法 + 登录gate/连败短路/合成cell(Phase 3a T4)"
```

---

## Task 5: 前端数据层 —— 读 fail_reason + failReasonLabel 映射

**Files:**
- Modify: `frontend/src/components/monitor/geo/geoDetail.ts`(`RawCell` + `PlatformVM` + `cellToPlatform` + 新增 `failReasonLabel`)
- Test: `frontend/src/components/monitor/geo/__tests__/geoDetail.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `__tests__/geoDetail.spec.ts` 追加(import 里加 `failReasonLabel`;`cellToPlatform` 是模块私有,测试改经 `failReasonLabel` + `PlatformVM.failReason` 字段验证):

```python
# —— 注意:这是 TS/vitest,下面用 TS 语法 ——
```

```ts
import { failReasonLabel } from "@/components/monitor/geo/geoDetail";

describe("failReasonLabel", () => {
  it("已知 code 映射人话 + 行动提示", () => {
    expect(failReasonLabel("not_logged_in")).toContain("未登录");
    expect(failReasonLabel("timeout")).toContain("超时");
    expect(failReasonLabel("rate_limited")).toContain("限流");
    expect(failReasonLabel("quota_exhausted")).toMatch(/配额|余额|欠费/);
    expect(failReasonLabel("content_blocked")).toMatch(/内容|拦/);
    expect(failReasonLabel("selector_drift")).toMatch(/改版|页面|采集/);
    expect(failReasonLabel("network")).toMatch(/网络|浏览器/);
    expect(failReasonLabel("interrupted")).toMatch(/中断/);
  });
  it("空 / unknown / 未知 code 回退旧文案「够不到平台」", () => {
    expect(failReasonLabel("")).toBe("够不到平台");
    expect(failReasonLabel("unknown")).toBe("够不到平台");
    expect(failReasonLabel("这不是已知code")).toBe("够不到平台");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/monitor/geo/__tests__/geoDetail.spec.ts`
Expected: FAIL —— `failReasonLabel` 未 export。

- [ ] **Step 3: 实现**

`geoDetail.ts` —— `PlatformVM` 加可选字段(在 `status` 后):

```ts
export interface PlatformVM {
  id: string;
  name: string;
  status: string; // 'ok' | 'error' | 'blocked' | 'empty' ...
  failReason?: string; // 失败原因分类(后端 geo.fail_reason;非失败 cell 为空)
  mentioned: boolean;
  // …其余不变…
```

`RawCell` 加可选字段(在 `status` 后):

```ts
interface RawCell {
  platform: string;
  keyword: string;
  mentioned: boolean | number;
  rank: number;
  sentiment: string;
  status: string;
  fail_reason?: string;
  answer_text: string;
  citations: RawCite[];
  recommended: RecommendedEntity[];
  summary: string;
}
```

`cellToPlatform` —— 映射 fail_reason(在 return 对象里加一行):

```ts
  return {
    id: c.platform,
    name: platformLabel(c.platform),
    status: c.status,
    failReason: c.fail_reason || "",
    mentioned,
    // …其余不变…
```

`geoDetail.ts` —— 在 `cellStatus`(约 `:219`)附近新增导出映射函数:

```ts
/**
 * 失败原因 code → 人话 + 行动提示(替掉写死的「够不到平台」)。
 * 与后端 csm_core/monitor/geo/fail_reason.py 的 FailReason 枚举对齐。
 * 空 / unknown / 未知 code 回退旧文案「够不到平台」,保证永不显示裸 code。
 */
const FAIL_REASON_TEXT: Record<string, string> = {
  not_logged_in: "未登录 · 去设置登录",
  timeout: "响应超时 · 可重试",
  selector_drift: "页面改版 · 采集异常",
  rate_limited: "被限流 · 稍后重试",
  quota_exhausted: "配额/余额不足 · 查账户",
  content_blocked: "内容被拦 · 换个说法",
  network: "网络/浏览器异常 · 重试",
  interrupted: "已中断 · 重跑一次",
};
export function failReasonLabel(code: string | undefined | null): string {
  return FAIL_REASON_TEXT[(code || "").trim()] ?? "够不到平台";
}
```

- [ ] **Step 4: 跑测试 + 类型检查**

Run:
```powershell
npx vitest run src/components/monitor/geo/__tests__/geoDetail.spec.ts
npx vue-tsc --noEmit -p tsconfig.app.json
```
Expected: vitest PASS(新 `failReasonLabel` 用例 + 既有全绿);vue-tsc 无错。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/components/monitor/geo/geoDetail.ts frontend/src/components/monitor/geo/__tests__/geoDetail.spec.ts
git commit -m "feat(geo-fe): cellToPlatform 读 fail_reason + failReasonLabel 映射(Phase 3a T5)"
```

---

## Task 6: 前端展示 —— 替换 Strip / Block 写死文案

**Files:**
- Modify: `frontend/src/components/monitor/geo/GeoPlatformStrip.vue:12-19`(import)、`:68`(副标题)
- Modify: `frontend/src/components/monitor/geo/GeoPlatformBlock.vue`(失败正文)
- 验证:vue-tsc 类型检查 + Task 5 的 `failReasonLabel` 单测已覆盖逻辑(模板接线本身无独立单测,靠类型检查 + Task 7 真机/构建确认)

- [ ] **Step 1: 改 GeoPlatformStrip**

`GeoPlatformStrip.vue` —— import 加 `failReasonLabel`:

```ts
import {
  cellStatus,
  failReasonLabel,
  isFailed,
  isPending,
  sentDotColor,
  sentLabel,
  type PlatformVM,
} from "@/components/monitor/geo/geoDetail";
```

`:68` 副标题 —— 失败分支改用 `failReasonLabel(p.failReason)`:

```vue
        <div :style="{ fontSize: '10px', color: 'var(--ink-3)', marginTop: '3px' }">
          {{ isPending(p) ? "待采集" : isFailed(p) ? failReasonLabel(p.failReason) : `引用 ${p.citations} · ${sentLabel(p.sentiment)}` }}
        </div>
```

- [ ] **Step 2: 改 GeoPlatformBlock**

`GeoPlatformBlock.vue` —— import 加 `failReasonLabel`(在既有 `isFailed` import 处),把失败正文(`:118` 附近「本平台本次采集失败，未取到结果。」)改为带原因:

```vue
      本平台本次{{ failReasonLabel(platform.failReason) }}，未取到结果。
```

> 若该处文案在模板里是纯静态字符串,改成上面的插值即可;`platform` 是该组件的 `props.platform`(`PlatformVM`,已含 `failReason`)。import 段照 `GeoPlatformStrip` 同样加 `failReasonLabel`。

- [ ] **Step 3: 类型检查 + 构建冒烟**

Run(在 `frontend/`):
```powershell
npx vue-tsc --noEmit -p tsconfig.app.json
npx vitest run src/components/monitor/geo/__tests__/geoDetail.spec.ts
```
Expected: 无类型错误;既有前端测试全绿。

- [ ] **Step 4: 提交**

```powershell
git add frontend/src/components/monitor/geo/GeoPlatformStrip.vue frontend/src/components/monitor/geo/GeoPlatformBlock.vue
git commit -m "feat(geo-fe): Strip/Block 用 failReasonLabel 替换写死「够不到平台」(Phase 3a T6)"
```

---

## Task 7: 全量回归 + 对抗性审查

**Files:** 无代码改动(除非发现回归);产出审查结论。

- [ ] **Step 1: Python 全量 geo + sidecar**

Run:
```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\objective-moore-ecce71;D:\CSM\.claude\worktrees\objective-moore-ecce71\sidecar"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest tests/core/monitor/geo/ -q
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/ -q
```
Expected: 全绿(geo 138+ 核心 + 新增测试;sidecar geo_routes 不受影响)。

- [ ] **Step 2: 前端全量 + 类型检查**

Run(在 `frontend/`):
```powershell
npx vitest run
npx vue-tsc --noEmit -p tsconfig.app.json
```
Expected: 全绿。若 `vitest run` 触发 `vite.config.js` 被 emit,`git checkout -- vite.config.js` 还原(见记忆坑)。

- [ ] **Step 3: 对抗性审查(用户全局规则 2 —— 长期授权,无需再问)**

并行派 3 个独立 subagent(Agent 工具,视角互斥,指令为「设法证伪、找问题」):
1. **正确性/契约**:`_rpa_batch` gate/短路 的 local_idx 是否始终连续 0..len-1、合成 cell 是否恰好补足 runner「漏产」契约、gate 与短路同时满足时是否重复 yield(li==0 且 consec_skip==1 的边界)、cancel 在合成 emission 中途是否仍安全。
2. **回归/边界**:v10 迁移对已有 v9 库幂等吗、旧 cell(无 fail_reason 列)读出是否为 ""、record_run 加列是否破坏既有 leaderboard/exposure_window 断言、`failReasonLabel` 对 undefined/裸 code 是否恒回退、`cellStatus`/`isFailed` 语义未变。
3. **数据可信/前端**:合成 blocked cell 是否真的不进 SoC/首推率分母(metrics)、不触发 `platform_dropped` 假告警(alerts)、L1「部分失败」徽标(`error_cells>0`)与全跳时的假「监测完成」守卫是否仍成立、前端占位卡(pending)与失败卡(fail)不混淆。

发现逐条核实:真问题修复 + 补回归测试并简要复审,误报说明理由。

- [ ] **Step 4: 审查结论汇总 + 最终提交(若有修复)**

在回复中附:发现什么 / 修了什么 / 放行什么。若审查触发修复,合并提交:

```powershell
git add -A
git commit -m "harden(geo): Phase 3a 对抗审查修复(<简述>)"
```

- [ ] **Step 5: 更新记忆**

更新 `project_csm_geo_collection_upgrade.md`:Phase 3a(诊断链路 + 跳过安全)已交付,列关键决策(fail_reason 9 类 / v10 列 / gate+短路+合成 cell / 前端 failReasonLabel 回退「够不到平台」);记 Phase 3b 待做(选择器兜底/超时验尸/中断分类/轮询降本/防风控节奏)。同步 `MEMORY.md` 一行。

---

## Self-Review(计划自检,写完对照 spec 一次)

**1. Spec 覆盖(Phase 3a 认领的 spec 章节):**
- §4.4 错误分类 + 真实原因传导 → Task 1(枚举+分类器)+ Task 2(v10 列)+ Task 3(回填)+ Task 5/6(前端映射+展示)✓
- §4.5 合成 cell(被跳平台不缺席)→ Task 4(gate/短路都发合成 cell,补足 runner 契约)✓
- §4.3 的「登录 gate(advisory,首格 blocked 跳过)」+「连败短路(轻量规则,3 连败跳过)」→ Task 4 ✓
- §4.3 其余(选择器兜底 / 超时验尸 / 中断分类 / 轮询降本)→ **Phase 3b**(明确不在本计划)。
- §4.2 防风控节奏(jitter/洗牌/启动抖动/run-window)→ **Phase 3b**。
- §4.6/§4.7(多采样/完整度)→ **Phase 4**。

**2. Placeholder 扫描:** 无 TBD/TODO;每个 code step 给了完整代码;测试有真实断言。✓

**3. 类型一致性:**
- `classify_fail_reason(*, status, error) -> str`:Task 1 定义,Task 3/4 同签名调用 ✓
- `GeoCell.fail_reason: str`:Task 1 加,Task 2 record_run 写 `c.fail_reason`,Task 3/4 构造时传 ✓
- `apply_v10_migration(conn)`:Task 2 定义于 geo/storage.py,同 Task 在 monitor/storage.py 调用 ✓
- `_rpa_batch(self, plat, plat_keywords, tok, *, web_search, brand, aliases, client, consec_skip)`:Task 4 方法签名,fetch lambda 传 6 个 kwargs 一致 ✓
- `failReasonLabel(code) -> string`:Task 5 定义,Task 6 在 .vue 调用,`PlatformVM.failReason?: string` / `RawCell.fail_reason?: string` 对齐 ✓
- 合成 cell `status="blocked"` + `raw.synthetic=True`:Task 4 产,Task 7 审查项验证其 KPI/告警安全 ✓

**4. 契约风险复核:** Task 4 的 gate/短路都通过 `_synthetic` 覆盖 `[当前+1, len)`,保证每平台恰好 yield `len(plat_keywords)` 个 cell —— 满足 `runner._rpa_worker` 的「漏产」检查(`runner.py:111`);local_idx 恒在 `[0, len)`,满足边界检查(`runner.py:94`)。✓
