# GEO 采集升级 Phase 2 实施计划 —— RPA 浏览器复用 + goto 会话重置

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 RPA 平台(Kimi/DeepSeek/元宝)从「每关键词重开一次 Chrome」改成「每平台开一次浏览器、跨关键词复用、每关键词用 `page.goto` 重置会话」,消除 RPA 最大的墙钟浪费,同时用 goto 重置堵住复用带来的会话污染(致命修复①)。

**Architecture:** 三个 RPA provider 的 `query()` 体本就 ~90% 相同,差异全部可由 `SiteSpec` 字段表达。抽出一个**规格驱动的共享 per-keyword 流程** `_driver.run_one_keyword(page, spec, kw)`;每个 provider 保留一个极小的 `session()` 上下文管理器(开浏览器 + 登录检查**一次**,`rpa_page` 仍在各自模块内调用→现有测试的 patch 生效),yield 一个复用该 page 的 `query_one(kw)`。`query()`(单发,向后兼容)委托给 `session()`。调度器 `run_cells_dual_lane` 加一个可选的 `rpa_batch` 生成器钩子(默认 None = Phase 1 逐 cell 行为,现有 runner/adapter 测试不变);`fetch()` 注入 `rpa_batch`——每平台开一次 session、循环关键词(query_one + extract + 隔离)、逐 cell yield。

**Tech Stack:** Python 3.12,patchright(现有 `_session`/`_flow` 原语不改),`contextlib`,pytest。前端不涉及。

**Spec:** `docs/superpowers/specs/2026-07-09-geo-collection-upgrade-design.md`(§B RPA 车道复用、§4.2 会话重置/节奏、致命修复①)

**范围边界:** 只做**浏览器复用 + goto 会话重置**(+ 把 3 平台并发的既有能力接到复用上)。防风控**节奏(jitter/洗牌/启动抖动)= Phase 3**;fail-fast gate / 合成 cell / 连败短路 / 真实原因传导 = Phase 3;多采样/完整度 = Phase 4。本 Phase 沿用 Phase 1 的失败语义(未登录→blocked cell、异常→error cell、逐 cell 隔离)。

**⚠ 真机校准是硬验收门(见 Task 6):** 单测只能验**结构**(浏览器开一次、每关键词 goto、登录检查一次、cell 隔离)。`page.goto(url)` 是否真的在 kimi/deepseek/元宝 上**重置对话**、复用浏览器 27 关键词是否稳、信源是否照旧抓到 —— 这些是真实 DOM 行为,**只能由用户在真机登录态下跑一遍确认**。本 Phase 的代码在单测全绿后仍**必须**过 Task 6 才算完成。

**运行测试:**
```
cd "D:/CSM/.claude/worktrees/objective-moore-ecce71"
export PYTHONPATH="D:/CSM/.claude/worktrees/objective-moore-ecce71;D:/CSM/.claude/worktrees/objective-moore-ecce71/sidecar"
"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/ -q
```
基线 129 passed(Phase 1 结束态)。

---

## 文件结构

- **修改** `csm_core/monitor/geo/providers/rpa/sites.py` —— `SiteSpec` 加 `stream_timeout_s: float`(把 provider 里硬编码的 120/180s 收进来)+ `post_new_chat_wait_ms: int`(元宝 600ms)。
- **新建** `csm_core/monitor/geo/providers/rpa/_driver.py` —— 规格驱动的共享 per-keyword 流程 `run_one_keyword(page, spec, keyword, *, web_search, cancel_token, logged_in)`(纯用 `_flow` 原语,无浏览器生命周期)。
- **修改** `csm_core/monitor/geo/providers/rpa/deepseek.py` / `kimi.py` / `yuanbao.py` —— 各加 `session()` 上下文管理器(开 `rpa_page` + goto + 登录一次,yield `query_one`),`query()` 改为委托 `session()`;删掉搬进 `_driver` 的重复流程。
- **修改** `csm_core/monitor/geo/runner.py` —— `run_cells_dual_lane` 加可选 `rpa_batch` 生成器钩子;`_rpa_worker` 有 batch 时调一次、逐 cell 就位并 `_tick`。
- **修改** `csm_core/monitor/platforms/geo_query.py` —— `fetch()` 构造 `_rpa_batch(plat, keywords, cancel_token)` 生成器(开 session、循环 query_one + extract + 隔离、逐 cell yield),传给 runner。
- **测试** `tests/core/monitor/geo/test_rpa_driver.py`(新)、`test_geo_runner.py`(+batch 钩子)、`test_geo_query_adapter.py`(+RPA 复用车道)、`test_rpa_providers.py`(应保持绿,验证 patch 仍生效)。

---

## Task 1: SiteSpec 收纳 per-site 超时 + 新会话等待

**Files:**
- Modify: `csm_core/monitor/geo/providers/rpa/sites.py`
- Test: `tests/core/monitor/geo/test_rpa_sites.py`(新)

- [ ] **Step 1: 写失败测试**

Create `tests/core/monitor/geo/test_rpa_sites.py`:

```python
from csm_core.monitor.geo.providers.rpa.sites import SITES


def test_specs_carry_stream_timeout_and_new_chat_wait():
    # per-site 超时从 provider 硬编码收进 SiteSpec(deepseek/yuanbao 180s、kimi 120s)。
    assert SITES["deepseek"].stream_timeout_s == 180.0
    assert SITES["kimi"].stream_timeout_s == 120.0
    assert SITES["yuanbao"].stream_timeout_s == 180.0
    # 元宝新会话后需等 composer 渲染(原 provider 里的 600ms)。
    assert SITES["yuanbao"].post_new_chat_wait_ms == 600
    assert SITES["deepseek"].post_new_chat_wait_ms == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_rpa_sites.py -v`
Expected: FAIL — `AttributeError: 'SiteSpec' object has no attribute 'stream_timeout_s'`

- [ ] **Step 3: 加字段**

In `csm_core/monitor/geo/providers/rpa/sites.py`, add two fields to the `SiteSpec` dataclass (after `exclude_hosts`):

```python
    stream_timeout_s: float = 120.0   # wait_stream_done 超时(深度思考/联网更慢的站放宽)
    post_new_chat_wait_ms: int = 0     # 点「新建对话」后等 composer 渲染就绪的毫秒数(元宝需要)
```

Then set them in the three specs: `deepseek` → `stream_timeout_s=180.0`; `kimi` → `stream_timeout_s=120.0` (explicit, matches default但显式写出); `yuanbao` → `stream_timeout_s=180.0, post_new_chat_wait_ms=600`.

- [ ] **Step 4: 运行确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_rpa_sites.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/geo/providers/rpa/sites.py tests/core/monitor/geo/test_rpa_sites.py
git commit -m "feat(geo-rpa): SiteSpec 收纳 per-site stream_timeout_s + post_new_chat_wait_ms"
```

---

## Task 2: 共享 per-keyword 流程 `_driver.run_one_keyword`

**Files:**
- Create: `csm_core/monitor/geo/providers/rpa/_driver.py`
- Test: `tests/core/monitor/geo/test_rpa_driver.py`(新)

- [ ] **Step 1: 写失败测试(fake page,验规格驱动的分支 + goto 重置 + blocked)**

Create `tests/core/monitor/geo/test_rpa_driver.py`:

```python
from __future__ import annotations
import pytest
from csm_core.monitor.geo.providers.rpa import _driver, _flow
from csm_core.monitor.geo.providers.rpa.sites import SITES


class _FakeKeyboard:
    def type(self, *a, **k): pass
    def press(self, *a, **k): pass


class _FakePage:
    def __init__(self, html):
        self._html = html
        self.keyboard = _FakeKeyboard()
        self.gotos = []
    def goto(self, url, *a, **k): self.gotos.append(url)
    def wait_for_timeout(self, *a, **k): pass
    def content(self): return self._html
    def query_selector(self, sel): return None
    def query_selector_all(self, sel): return []
    def evaluate(self, *a, **k): return False
    def click(self, *a, **k): pass


def test_run_one_keyword_blocked_when_not_logged_in():
    page = _FakePage("<html></html>")
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "k",
                                  web_search=True, cancel_token=None, logged_in=False)
    assert ans.status == "blocked"
    assert "登录" in ans.error
    assert page.gotos == []                      # 未登录不 goto,直接 blocked


def test_run_one_keyword_resets_conversation_via_goto(monkeypatch):
    # 每关键词必须 goto 回首页重置会话(致命修复①)。wait_stream_done patch 成 no-op。
    monkeypatch.setattr(_flow, "wait_stream_done", lambda *a, **k: None)
    html = ('<textarea></textarea>'
            '<div class="ds-markdown ds-assistant-message-main-content">推荐小鹏G6 '
            '<a href="https://zhuanlan.zhihu.com/p/9">知乎</a></div>')
    page = _FakePage(html)
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "家用吸尘器",
                                  web_search=True, cancel_token=None, logged_in=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
    assert ans.citations[0].url == "https://zhuanlan.zhihu.com/p/9"
    assert page.gotos == ["https://chat.deepseek.com/"]   # 确实 goto 重置了一次


def test_run_one_keyword_empty_when_no_answer(monkeypatch):
    monkeypatch.setattr(_flow, "wait_stream_done", lambda *a, **k: None)
    page = _FakePage('<textarea></textarea>'
                     '<div class="ds-markdown ds-assistant-message-main-content"></div>')
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "k",
                                  web_search=True, cancel_token=None, logged_in=True)
    assert ans.status == "empty"
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_rpa_driver.py -v`
Expected: FAIL — `ModuleNotFoundError: ... rpa._driver` / `AttributeError: run_one_keyword`

- [ ] **Step 3: 写 `_driver.run_one_keyword`(统一三站 per-keyword 流程)**

Create `csm_core/monitor/geo/providers/rpa/_driver.py`:

```python
"""规格驱动的 RPA per-keyword 流程(三站统一;差异全在 SiteSpec)。

只做「在一个已开好、已登录的 page 上,对单个关键词跑一轮采集」——不管浏览器
生命周期(由 provider.session 负责开/关一次)。每轮先 page.goto 回首页重置会话,
避免复用浏览器时上一关键词的上下文污染本轮(致命修复①)。
"""
from __future__ import annotations
import threading
from typing import Any

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _flow
from csm_core.monitor.geo.providers.rpa.sites import SiteSpec


def run_one_keyword(page: Any, spec: SiteSpec, keyword: str, *, web_search: bool,
                    cancel_token: "threading.Event | None", logged_in: bool) -> GeoAnswer:
    if not logged_in:
        return GeoAnswer(platform=spec.platform, keyword=keyword, status="blocked",
                         error=f"{spec.platform} 未登录，请在设置中登录")
    # 会话重置(fix #1):回首页 →(有新建按钮的站)开干净会话,清掉上一关键词上下文。
    page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
    if spec.new_chat_sel:
        _flow.start_new_chat(page, new_chat_sel=spec.new_chat_sel, answer_sel=spec.answer_sel)
        if spec.post_new_chat_wait_ms:
            page.wait_for_timeout(spec.post_new_chat_wait_ms)
    maybe_cancel(cancel_token)
    if spec.deep_think:
        _flow.enable_toggle_by_text(page, text="深度思考")
    if web_search and spec.web_toggle_sel:
        _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
    if web_search and spec.tool_web_search:
        _flow.enable_tool_web_search(page, tool_sel=spec.tool_web_search[0],
                                     item_text=spec.tool_web_search[1])
    maybe_cancel(cancel_token)
    _flow.submit_query(page, composer_sel=spec.composer_sel, send_sel=spec.send_sel, text=keyword)
    done_pred = _flow.make_done_predicate(page, generating_sel=spec.generating_sel,
                                          answer_sel=spec.answer_sel)
    _flow.wait_stream_done(page, done_predicate=done_pred, idle_ms=1500,
                           timeout_s=spec.stream_timeout_s, cancel_token=cancel_token)
    html = page.content()
    answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
    if spec.toolcall_sel:                 # Kimi:点开「搜索网页」toolcall 再全页抓 <a>
        _flow.expand_search_toolcalls(page, toolcall_sel=spec.toolcall_sel)
        html = page.content()
        cites = _flow.extract_citations(html, container_sel=None, exclude_hosts=spec.exclude_hosts)
    elif spec.source_text_sel:            # 元宝:COT 里 name-only 信源(无 URL)
        cites = _flow.parse_source_items(html, item_sel=spec.source_text_sel)
    else:                                 # DeepSeek:答案容器内 <a>
        cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                        exclude_hosts=spec.exclude_hosts)
    return GeoAnswer(platform=spec.platform, keyword=keyword, answer_text=answer,
                     citations=cites, status="ok" if answer else "empty",
                     raw={"html_len": len(html), "cite_n": len(cites)})
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_rpa_driver.py -v`
Expected: PASS(3 个)

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/geo/providers/rpa/_driver.py tests/core/monitor/geo/test_rpa_driver.py
git commit -m "feat(geo-rpa): 规格驱动共享 per-keyword 流程 _driver.run_one_keyword(含 goto 会话重置)"
```

---

## Task 3: 三个 provider 加 `session()` + `query()` 委托(保持现有测试绿)

**Files:**
- Modify: `csm_core/monitor/geo/providers/rpa/deepseek.py` / `kimi.py` / `yuanbao.py`
- Test: `tests/core/monitor/geo/test_rpa_providers.py`(应保持绿,不改)

- [ ] **Step 1: 先确认现有 RPA provider 测试是基线绿**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_rpa_providers.py -v`
Expected: 全绿(重构后必须仍全绿——这就是本 Task 的验收)。

- [ ] **Step 2: 重写 `deepseek.py`(session + query 委托)**

Replace the body of `class DeepSeekProvider` in `csm_core/monitor/geo/providers/rpa/deepseek.py` with:

```python
import contextlib

class DeepSeekProvider:
    platform = "deepseek"
    mode = "rpa"

    @contextlib.contextmanager
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None):
        """开浏览器 + 登录检查**一次**,yield query_one(keyword) 复用同一 page。"""
        spec = _SPEC
        with rpa_page(self.platform, headless=False) as page:
            page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
            logged_in = _flow.wait_login_ready(page, logged_in_sel=spec.logged_in_sel,
                                               logged_out_sel=spec.logged_out_sel)

            def query_one(keyword: str) -> GeoAnswer:
                return _driver.run_one_keyword(page, spec, keyword, web_search=web_search,
                                               cancel_token=cancel_token, logged_in=logged_in)
            yield query_one

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        """单发(向后兼容):开一次 session 只问一个关键词。"""
        maybe_cancel(cancel_token)
        try:
            with self.session(web_search=web_search, cancel_token=cancel_token) as query_one:
                return query_one(keyword)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo-rpa][deepseek] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

Add `from csm_core.monitor.geo.providers.rpa import _driver` to the imports. Keep the existing `rpa_page`, `_flow`, `maybe_cancel`, `is_cancelled`, `_SPEC`, `logger` imports (the tests patch `ds.rpa_page` and `ds._flow` — both must remain module-level names in this file).

- [ ] **Step 3: 同法重写 `kimi.py`**

Same shape in `csm_core/monitor/geo/providers/rpa/kimi.py` — `class KimiProvider` with `session()` (identical body but `platform="kimi"`, `_SPEC = SITES["kimi"]`) and `query()` delegating. Add `from ...rpa import _driver`. The Kimi-specific toolcall citation logic now lives in `_driver.run_one_keyword` (gated on `spec.toolcall_sel`), so it must NOT be duplicated here.

```python
import contextlib

class KimiProvider:
    platform = "kimi"
    mode = "rpa"

    @contextlib.contextmanager
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None):
        spec = _SPEC
        with rpa_page(self.platform, headless=False) as page:
            page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
            logged_in = _flow.wait_login_ready(page, logged_in_sel=spec.logged_in_sel,
                                               logged_out_sel=spec.logged_out_sel)

            def query_one(keyword: str) -> GeoAnswer:
                return _driver.run_one_keyword(page, spec, keyword, web_search=web_search,
                                               cancel_token=cancel_token, logged_in=logged_in)
            yield query_one

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        try:
            with self.session(web_search=web_search, cancel_token=cancel_token) as query_one:
                return query_one(keyword)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo-rpa][kimi] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

- [ ] **Step 4: 同法重写 `yuanbao.py`**

Same shape in `csm_core/monitor/geo/providers/rpa/yuanbao.py` — `class YuanbaoProvider`, `platform="yuanbao"`, `_SPEC = SITES["yuanbao"]`. 元宝的 new_chat / deep_think / tool_web_search / source_text 信源全部已由 `_driver.run_one_keyword` 按 `_SPEC` 字段驱动,这里**不再重复**。Add `from ...rpa import _driver`.

```python
import contextlib

class YuanbaoProvider:
    platform = "yuanbao"
    mode = "rpa"

    @contextlib.contextmanager
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None):
        spec = _SPEC
        with rpa_page(self.platform, headless=False) as page:
            page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
            logged_in = _flow.wait_login_ready(page, logged_in_sel=spec.logged_in_sel,
                                               logged_out_sel=spec.logged_out_sel)

            def query_one(keyword: str) -> GeoAnswer:
                return _driver.run_one_keyword(page, spec, keyword, web_search=web_search,
                                               cancel_token=cancel_token, logged_in=logged_in)
            yield query_one

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        try:
            with self.session(web_search=web_search, cancel_token=cancel_token) as query_one:
                return query_one(keyword)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo-rpa][yuanbao] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

- [ ] **Step 5: 运行现有 RPA provider 测试确认仍全绿**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_rpa_session.py tests/core/monitor/geo/test_registration.py -v`
Expected: 全绿。若 `wait_stream_done` 的 patch 不再生效(测试挂在真实轮询超时),检查 `_driver` 是否用 `from . import _flow` 引同一模块对象(必须);若 `rpa_page` patch 不生效(测试打真浏览器),检查 `session()` 是否在 provider 模块内直接调 `rpa_page`(必须,不能从 `_driver` 调)。

> **为什么现有测试能存活(实现者须理解):** 测试 `monkeypatch.setattr(ds, "rpa_page", fake)` 改的是 deepseek 模块里的 `rpa_page` 名——`session()` 就在该模块内调它,patch 生效。测试 `monkeypatch.setattr(ds._flow, "wait_stream_done", x)` 改的是**共享 `_flow` 模块**的属性——`_driver` 也 `from . import _flow`,是同一模块对象,patch 同样生效。

- [ ] **Step 6: 提交**

```bash
git add csm_core/monitor/geo/providers/rpa/deepseek.py csm_core/monitor/geo/providers/rpa/kimi.py csm_core/monitor/geo/providers/rpa/yuanbao.py
git commit -m "refactor(geo-rpa): 三站 provider 拆 session()/query() 委托共享 _driver(去重、为复用铺路)"
```

---

## Task 4: 调度器 `run_cells_dual_lane` 加 `rpa_batch` 复用钩子

**Files:**
- Modify: `csm_core/monitor/geo/runner.py`
- Test: `tests/core/monitor/geo/test_geo_runner.py`(+新测)

- [ ] **Step 1: 写失败测试(fake batch 生成器,无真浏览器)**

Append to `tests/core/monitor/geo/test_geo_runner.py`:

```python
def test_rpa_batch_hook_places_cells_and_ticks_progress():
    # rpa_batch 提供时,RPA 平台走「每平台一次 batch」路径:逐 cell 就位 + 逐 cell 进度。
    plan = [("k1", "kimi"), ("k2", "kimi"), ("k1", "tongyi")]
    seen_batches = []

    def rpa_batch(plat, keywords, cancel_token):
        seen_batches.append((plat, tuple(keywords)))
        for li, kw in enumerate(keywords):
            yield li, _cell(kw, plat)          # 模拟复用浏览器逐关键词产出

    def run_cell(kw, plat):                     # 只应被 API 平台(tongyi)调用
        return _cell(kw, plat)

    prog = []
    out = runner.run_cells_dual_lane(
        plan, run_cell, mode_of=lambda p: "api" if p == "tongyi" else "rpa",
        api_pool_size=4, rpa_platform_concurrency=3,
        progress_cb=lambda c, t: prog.append((c, t)), rpa_batch=rpa_batch)

    assert [(c.keyword, c.platform) for c in out] == plan   # 顺序保持
    assert seen_batches == [("kimi", ("k1", "k2"))]         # kimi 只开一次 batch,含两个关键词
    assert prog[-1] == (3, 3)                                # 3 个 cell 全计进度
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py::test_rpa_batch_hook_places_cells_and_ticks_progress -v`
Expected: FAIL — `TypeError: run_cells_dual_lane() got an unexpected keyword argument 'rpa_batch'`

- [ ] **Step 3: 加 `rpa_batch` 钩子**

In `csm_core/monitor/geo/runner.py`:

1. Add param `rpa_batch=None` to the signature (after `cancel_token`):
```python
    cancel_token: "threading.Event | None" = None,
    rpa_batch: "Callable[[str, list[str], threading.Event | None], Any] | None" = None,
```
2. Replace `_rpa_worker` with a batch-aware version:
```python
    def _rpa_worker(plat: str, indices: "list[int]") -> None:
        if rpa_batch is None:                       # Phase-1 回退:逐 cell(每 cell 自开浏览器)
            for i in indices:
                if cancelled["exc"] is not None:
                    return
                _one(i)
            return
        keywords = [cells_plan[i][0] for i in indices]
        try:
            for local_idx, cell in rpa_batch(plat, keywords, cancel_token):
                if cancelled["exc"] is not None:
                    return
                results[indices[local_idx]] = cell
                _tick()
        except BaseException as e:                  # noqa: BLE001
            if is_cancelled(e):
                cancelled["exc"] = e
                return
            raise
```
3. Update the `_rpa_worker` submit call to pass the platform name (it currently receives only `indices`). Change the submit loop:
```python
        for plat_name, indices in rpa_groups.items():
            futs.append(rpa_ex.submit(_rpa_worker, plat_name, indices))
```
(`rpa_groups` is already keyed by platform, so iterate `.items()`.)

- [ ] **Step 4: 运行确认通过 + 全 runner 测试回归**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py -v`
Expected: 全绿(新测 + 原有 6 个;`rpa_batch=None` 默认保证原有测试语义不变)。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/geo/runner.py tests/core/monitor/geo/test_geo_runner.py
git commit -m "feat(geo): runner 加 rpa_batch 复用钩子(每平台一次 batch;默认 None 回退逐 cell)"
```

---

## Task 5: `fetch()` 注入 `_rpa_batch`(开 session、循环 query_one + extract + 隔离)

**Files:**
- Modify: `csm_core/monitor/platforms/geo_query.py`
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py`(+新测)

- [ ] **Step 1: 写失败测试(fake session provider,验复用 + 隔离,无真浏览器)**

Append to `tests/core/monitor/geo/test_geo_query_adapter.py`:

```python
def test_fetch_rpa_lane_reuses_session_per_platform(fresh_db, monkeypatch):
    # RPA 平台每平台只开一次 session,循环关键词;一个坏关键词只坏一个 cell,不拖垮整轮。
    import contextlib
    opens = {"n": 0}

    class _RpaProv:
        def __init__(self, p): self.platform = p; self.mode = "rpa"
        @contextlib.contextmanager
        def session(self, *, web_search=True, cancel_token=None):
            opens["n"] += 1
            from csm_core.monitor.geo.models import GeoAnswer
            def query_one(kw):
                if kw == "bad":
                    raise RuntimeError("selector drift")
                return GeoAnswer(platform=self.platform, keyword=kw, answer_text=f"{kw} 推荐 小鹏")
            yield query_one

    monkeypatch.setattr(geo_mod, "get_provider", lambda p: _RpaProv(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1", "bad", "k2"], "platforms": ["kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))

    assert opens["n"] == 1                        # kimi 只开一次 session(3 关键词复用)
    assert result.status == "ok"                  # 部分失败不整体失败
    assert result.metric["error_cells"] == 1      # 仅 "bad" 关键词失败
    conn = storage.get_conn()
    rows = {r["keyword"]: r["status"] for r in
            conn.execute("SELECT keyword,status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()}
    assert rows == {"k1": "ok", "bad": "error", "k2": "ok"}
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_query_adapter.py::test_fetch_rpa_lane_reuses_session_per_platform -v`
Expected: FAIL — `opens["n"] == 3`(当前逐 cell 每关键词各开一次 session),断言 `== 1` 失败。

- [ ] **Step 3: 加 `_rpa_batch` + 一个「在已开 session 上跑单 cell」的隔离助手,并传给 runner**

In `csm_core/monitor/platforms/geo_query.py`, add a helper method to `GeoQueryAdapter` (next to `_run_cell`):

```python
    def _run_cell_on_session(self, query_one, keyword, platform, brand, aliases, client) -> GeoCell:
        """在已开好的 RPA session 上跑单关键词:query_one → extract → cell(逐 cell 隔离,同 _run_cell)。"""
        try:
            answer = query_one(keyword)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="", raw={"error": answer.error})
            ext = extract(answer, brand=brand, aliases=aliases, client=client)
            return GeoCell(platform=platform, keyword=keyword,
                           mentioned=ext.mentioned, rank=ext.target_rank, sentiment=ext.sentiment,
                           answer_text=answer.answer_text, status="ok", raw=answer.raw,
                           citations=ext.citations, recommended=ext.recommended, summary=ext.summary)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo] rpa cell 失败 kw=%s plat=%s", keyword, platform)
            return GeoCell(platform=platform, keyword=keyword, status="error", raw={"error": repr(e)})
```

Then, inside `fetch()`, right before the `run_cells_dual_lane(...)` call, build the batch generator and pass it:

```python
        def _rpa_batch(plat: str, keywords: "list[str]", tok):
            """每平台开一次 session,循环关键词逐 cell yield(浏览器跨关键词复用)。
            provider 构造 / session 开启失败 → 该平台每个关键词各出一个 error cell(隔离)。"""
            try:
                provider = get_provider(plat)
                session_cm = provider.session(web_search=web_search, cancel_token=cancel_token)
            except Exception as e:                       # 构造失败:全隔离成 error
                for li, kw in enumerate(keywords):
                    yield li, GeoCell(platform=plat, keyword=kw, status="error", raw={"error": repr(e)})
                return
            produced = 0
            try:
                with session_cm as query_one:
                    for li, kw in enumerate(keywords):
                        maybe_cancel(cancel_token)
                        cell = self._run_cell_on_session(query_one, kw, plat, brand, aliases, client)
                        produced = li + 1
                        yield li, cell
            except Exception as e:                       # session 中途崩(浏览器死等):剩余关键词补 error
                if is_cancelled(e):
                    raise
                logger.exception("[geo] rpa session 中断 plat=%s", plat)
                for li in range(produced, len(keywords)):
                    yield li, GeoCell(platform=plat, keyword=keywords[li], status="error",
                                      raw={"error": f"session 中断: {e!r}"})

        maybe_cancel(cancel_token)
        tail = cells_plan[resume_from:]
        cells: list[GeoCell] = geo_runner.run_cells_dual_lane(
            tail, _cell,
            mode_of=lambda p: mode_map.get(p, "api"),
            api_pool_size=api_pool_size,
            rpa_platform_concurrency=rpa_conc,
            progress_cb=progress_cb,
            initial_done=resume_from,
            cancel_token=cancel_token,
            rpa_batch=_rpa_batch,
        )
```

(Delete the old `maybe_cancel(cancel_token)` [pre-runner] / `tail` / `run_cells_dual_lane(...)` block being replaced — the new one above supersedes it. `web_search`, `brand`, `aliases`, `client`, `cancel_token`, `get_provider` are all already in scope in `fetch()`.)

> **⚠ 必须保留 C1 修复:** runner 调用**之后**紧跟的那行 `maybe_cancel(cancel_token)`(Phase 1 加的**后置**取消复查,在 `agg = metrics.aggregate(cells)` 之前)**不要删** —— 它管「API cell 在飞时 Stop 被吞」的场景,与本 Task 无关。本 Task 只替换 runner 调用**及其之前**的块(新增 `_rpa_batch` 定义 + `rpa_batch=_rpa_batch` 参数),后置复查原样留着。跑 `test_fetch_cancel_midrun_not_swallowed_as_ok` 确认它仍绿。

- [ ] **Step 4: 运行新测 + 全 adapter/geo 回归**

Run:
```
"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_query_adapter.py -v
"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/ -q
```
Expected: 新测 PASS;全 geo 目录零回归(Phase-1 的 API 并发 / I1 隔离 / C1 取消 / 全失败 / 进度 各测仍绿)。注意 `test_fetch_uses_dual_lane_api_concurrent` 里的 fake provider **没有 `session()`**——它 `mode="api"`,走 API 车道不碰 `_rpa_batch`,不受影响。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/geo_query.py tests/core/monitor/geo/test_geo_query_adapter.py
git commit -m "feat(geo): fetch 注入 rpa_batch —— RPA 每平台复用浏览器跨关键词(cell 级隔离/中断补 error)"
```

---

## Task 6:【用户执行】真机校准 + 验收 + 对抗性审查

**Files:** 无(验证任务)。**本 Task 必须由用户在真机登录态下完成——单测覆盖不了真实 DOM 行为。**

- [ ] **Step 1: 全量单测回归(agent 可做)**

Run:
```
"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/ -q
"D:/CSM/.venv/Scripts/python.exe" -m pytest sidecar/tests/test_geo_routes.py sidecar/tests/test_geo_exposure_summary.py sidecar/tests/test_geo_leaderboard_global.py -q
```
Expected: 全绿。

- [ ] **Step 2:【用户】真机校准跑一个小任务(2–3 关键词 × 三个 RPA 平台,已登录)**,逐条确认:
  - **会话重置有效**:第 2、3 个关键词的回答**不含**前一关键词的品牌/上下文残留(goto 真的重置了 kimi/deepseek/元宝 的对话)。若某站 goto 后仍恢复旧会话 → 该站在 `sites.py` 补 `new_chat_sel` 或改重置手法。
  - **浏览器复用**:每个 RPA 平台**只弹一次** Chrome(不再每关键词重开);任务管理器里三站各一个 chrome 树、可同时在跑。
  - **信源照旧**:kimi 的引用数、元宝的 name-only 信源、deepseek 的答案内链接 —— 与 Phase 1 单发时口径一致(没因复用丢失)。
  - **超时口径**:深度思考的 deepseek/元宝 仍走 180s、kimi 120s(慢站不误判超时)。
  - **Stop 生效**:运行中点停止,能在合理时间内中止(RPA 每题 `wait_stream_done` 每 500ms 查 token;`page.goto`/登录阶段的 Stop 迟滞是已知、留 Phase 3)。
- [ ] **Step 3:【用户/agent】对抗性审查**(按用户全局规则):派 2–3 独立 subagent 证伪本 Phase——①并发正确性(3 session 并发、cell 就位/进度/取消传导、session 中断补 error 的下标正确性)②回归(现有 RPA provider 测试、Phase-1 契约)③资源/风控(3 长驻浏览器同时开的内存、profile 锁、复用后单会话多轮是否更像机器人——注意节奏是 Phase 3)。发现逐条核实修复。
- [ ] **Step 4: 收尾**:真机通过 + 审查通过后,`finishing-a-development-branch` 决定合并/PR。

---

## Self-Review(对照 spec)

- **spec §B / §4.2 RPA 浏览器跨关键词复用** → Task 3(session)+ Task 4(runner batch 钩子)+ Task 5(fetch 注入)。✓
- **spec §4.2 每关键词 goto 会话重置(致命修复①)** → Task 2 `run_one_keyword` 首步 `page.goto`;Task 6 真机验「无上下文污染」。✓
- **3 平台并发** → 沿用 Phase 1 的 `rpa_platform_concurrency`(runner `rpa_ex`);batch 钩子在其上跑,每平台一 worker。✓
- **cell 级隔离不回归** → Task 5 `_run_cell_on_session` 兜异常成 error cell、`_rpa_batch` 兜 provider 构造失败 + session 中断。✓
- **失败语义沿用 Phase 1**(未登录→blocked、异常→error、逐 cell) → `run_one_keyword` not-logged-in→blocked;`_run_cell_on_session` 异常→error。✓
- **不在本 Phase**:节奏(jitter/洗牌/启动抖动)、fail-fast gate、合成 cell、真实原因传导、多采样、完整度 → Phase 3/4,已在范围边界声明。✓
- **占位扫描**:无 TBD;每 code step 有完整代码。**唯一「非代码」验收 = Task 6 真机校准**,这是 RPA 真实 DOM 的固有约束,非占位。
- **类型/签名一致性**:`run_one_keyword(page, spec, keyword, *, web_search, cancel_token, logged_in)` 在 Task 2 定义、Task 3 三处调用一致;`session()`/`query_one` 契约在 Task 3 定义、Task 5 `_rpa_batch` 消费一致;runner `rpa_batch(plat, keywords, tok)` 在 Task 4 定义、Task 5 提供一致。✓
