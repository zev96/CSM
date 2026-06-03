# GEO 阶段 3：RPA 采集（DeepSeek / Kimi / 腾讯元宝）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AI 卡位监控新增「真浏览器 RPA」采集通道，覆盖 DeepSeek / Kimi / 腾讯元宝三家 API 拿不到联网信源的平台，产出与 API provider 同形的 `GeoAnswer`，下游全链路零改动复用。

**Architecture:** 在 `csm_core/monitor/geo/providers/rpa/` 下建共享基座（`_flow` 纯解析+page 原语、`_session` 持久档会话/登录、`sites` 逐站选择器常量）+ 3 个薄 provider。DOM 读取拆「纯函数（吃 HTML 串，bs4 解析，CI fixture 可测）+ 薄 page 包装」。登录走持久档 + 有头登录窗（镜像 baidu）。geo_query 串行化 + 透传 cancel_token。

**Tech Stack:** Python (patchright sync API, beautifulsoup4, httpx-free), pytest（fake page/session monkeypatch）, FastAPI route（`async def` + `asyncio.to_thread`）, Vue3 + vitest, PyInstaller hiddenimports。

**基线 spec:** `docs/superpowers/specs/2026-06-02-geo-phase3-rpa-design.md`
**工作树:** `D:/CSM/.claude/worktrees/geo-phase3`（分支 `claude/geo-phase3`，off origin/main d34786c）。以下命令 cwd 默认 = 工作树根（前端命令 cwd = `frontend/`）。

**⚠ 跑测试的命令前缀（必读）**：本 worktree 的 editable 安装指向主仓 `D:/CSM`，**必须用 `python -m pytest`**（cwd=worktree 把 worktree 放 sys.path[0]，覆盖 editable）+ `PYTHONPATH` 带上 sidecar，否则会测成主仓代码 / 找不到 worktree 新模块。各 Task 里写的 `pytest ...` 一律按下式跑（Windows git-bash，已实测 19 passed 基线绿）：
```bash
cd D:/CSM/.claude/worktrees/geo-phase3
PYTHONPATH="D:/CSM/.claude/worktrees/geo-phase3/sidecar" python -m pytest <路径> -v
```
csm_core 走 cwd 解析到 worktree；csm_sidecar 走 PYTHONPATH 解析到 worktree。前端命令 cwd=`frontend/`：`npm run test -- <名>`、`npx vue-tsc --noEmit`。**绝不**用裸 `pytest`。

---

## 设计契约（所有 Task 共享，签名以此为准，勿漂移）

**provider 契约**（`providers/base.py` 已有，零改）：
```python
class GeoProvider(Protocol):
    platform: str
    mode: str  # "api" | "rpa"
    def query(self, keyword: str, *, web_search: bool,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer: ...
```
`GeoAnswer`（`geo/models.py`）：`platform, keyword, answer_text:str, citations:list[Citation{url,title}], raw:dict, status:"ok"|"empty"|"blocked"|"error", error:str`。

**`_flow` 函数签名**（Task 1/2 定义，后续 Task 调用）：
- 纯函数：`extract_citations(html, *, container_sel=None, exclude_hosts=()) -> list[Citation]`、`extract_answer_text(html, *, container_sel=None) -> str`、`is_logged_in_html(html, *, logged_in_sel, logged_out_sel=None) -> bool`
- page 包装：`detect_login(page, *, logged_in_sel, logged_out_sel=None) -> bool`、`submit_query(page, *, composer_sel, send_sel, text) -> None`、`ensure_web_toggle(page, *, toggle_sel, want_on=True, on_attr="aria-pressed", on_value="true") -> None`、`wait_stream_done(page, *, done_predicate, idle_ms=1500, timeout_s=90.0, poll_ms=500, cancel_token=None) -> None`

**⚠ 选择器约束（关键，防 bug）**：传给 bs4 纯函数的选择器（`logged_in_sel / logged_out_sel / container_sel / answer_sel / citation_sel`）**必须是合法 CSS**——不能用 Playwright 的 `:has-text()` 等伪类（bs4 `.select()` 不认，会 `SelectorSyntaxError`）。只在 page 端用（`page.click/query_selector`）的选择器（`send_sel / web_toggle_sel / generating_sel`）才可用 Playwright 语法。

**`SiteSpec` 字段**（Task 3 定义）：`platform, url, composer_sel, send_sel, web_toggle_sel, generating_sel, answer_sel, citation_sel, logged_in_sel, logged_out_sel, exclude_hosts`。

**`_session` 函数**（Task 4）：`rpa_page(platform, *, headless=False)`（ctx mgr，yield page）、`login_status(platform) -> dict`（`{"logged_in": bool}`）、`open_login(platform, *, timeout_s=300) -> dict`（`{"status": "success"|"cancelled"|"timeout"|"error"}`）。

---

## File Structure（先锁定边界）

| 文件 | 职责 | 动作 |
|---|---|---|
| `csm_core/monitor/geo/providers/rpa/__init__.py` | 包标记 | 建（空） |
| `csm_core/monitor/geo/providers/rpa/_flow.py` | 站点无关交互原语 + 纯 HTML 解析 | 建 |
| `csm_core/monitor/geo/providers/rpa/sites.py` | 逐站选择器常量（`SiteSpec` + `SITES`） | 建（DeepSeek 起，Kimi/元宝逐 Task 加） |
| `csm_core/monitor/geo/providers/rpa/_session.py` | 持久档会话 `rpa_page` + 登录 `open_login`/`login_status` | 建 |
| `csm_core/monitor/geo/providers/rpa/deepseek.py` | DeepSeek provider | 建 |
| `csm_core/monitor/geo/providers/rpa/kimi.py` | Kimi RPA provider | 建（Task 9） |
| `csm_core/monitor/geo/providers/rpa/yuanbao.py` | 腾讯元宝 provider | 建（Task 10） |
| `csm_core/monitor/geo/providers/base.py` | `get_provider` 注册 | 改（加 deepseek/yuanbao 分支 + kimi 改指 rpa） |
| `csm_core/monitor/platforms/geo_query.py` | adapter | 改（cancel_token 透传 + 串行化） |
| `sidecar/csm_sidecar/routes/monitor.py` | 登录路由 | 改（加 2 个 geo rpa 路由） |
| `sidecar/csm-sidecar.spec` | 打包 hiddenimports | 改（加 rpa 模块） |
| `frontend/src/utils/monitor-types.ts` | `GEO_PLATFORMS` | 改（加 3 平台 + `mode` 字段） |
| `frontend/src/views/SettingsView.vue` | 「RPA 登录」设置分组 | 改 |
| `tests/core/monitor/geo/test_rpa_flow.py` | `_flow` 纯函数 + 原语测试 | 建 |
| `tests/core/monitor/geo/test_rpa_session.py` | `_session` 测试（fake playwright） | 建 |
| `tests/core/monitor/geo/test_rpa_providers.py` | 3 provider 错误路径测试 | 建 |
| `tests/core/monitor/geo/test_registration.py` | get_provider 注册 | 改（加 3 平台断言） |
| `tests/core/monitor/geo/test_geo_query_adapter.py` | adapter cancel 透传 | 改 |
| `sidecar/tests/test_monitor_routes.py` | geo rpa 登录路由测试 | 改 |
| `frontend/src/utils/__tests__/monitor-types.spec.ts` | `GEO_PLATFORMS` vitest | 建 |
| `CHANGELOG.md` | [Unreleased] 条目 | 改 |
| `docs/superpowers/plans/2026-06-02-geo-phase3-rpa-acceptance.md` | 人工验收清单 | 建（Task 11） |

---

## Task 1: `_flow` 纯 HTML 解析函数

**Files:**
- Create: `csm_core/monitor/geo/providers/rpa/__init__.py`
- Create: `csm_core/monitor/geo/providers/rpa/_flow.py`
- Test: `tests/core/monitor/geo/test_rpa_flow.py`

- [ ] **Step 1: 建包标记**

```bash
mkdir -p csm_core/monitor/geo/providers/rpa
printf '"""GEO RPA provider 子包（真浏览器采集 DeepSeek/Kimi/元宝）。"""\n' > csm_core/monitor/geo/providers/rpa/__init__.py
```

- [ ] **Step 2: 写失败测试（纯解析）**

`tests/core/monitor/geo/test_rpa_flow.py`：
```python
from csm_core.monitor.geo.providers.rpa import _flow


ANSWER_HTML = """
<html><body>
  <nav><a href="https://chat.deepseek.com/help">帮助</a></nav>
  <div class="answer">
    <p>推荐 小鹏G6，参考下列来源。</p>
    <a href="https://zhuanlan.zhihu.com/p/123">小鹏G6 实测 - 知乎</a>
    <a href="https://www.autohome.com.cn/x">汽车之家评测</a>
    <a href="https://zhuanlan.zhihu.com/p/123">重复链接</a>
    <a href="/relative/path">站内相对链接</a>
    <a href="https://chat.deepseek.com/self">自家域名</a>
  </div>
</body></html>
"""


def test_extract_citations_dedups_filters_and_excludes_hosts():
    cits = _flow.extract_citations(
        ANSWER_HTML, container_sel="div.answer",
        exclude_hosts=("chat.deepseek.com",))
    urls = [c.url for c in cits]
    assert urls == ["https://zhuanlan.zhihu.com/p/123",
                    "https://www.autohome.com.cn/x"]
    assert cits[0].title == "小鹏G6 实测 - 知乎"


def test_extract_citations_container_none_scans_whole_doc():
    cits = _flow.extract_citations(ANSWER_HTML)  # 无 container → 含 nav 的 help 链接
    assert any(c.url.endswith("/help") for c in cits)


def test_extract_answer_text_collapses_whitespace():
    txt = _flow.extract_answer_text(ANSWER_HTML, container_sel="div.answer")
    assert "小鹏G6" in txt
    assert "  " not in txt  # 空白已折叠


def test_extract_answer_text_missing_container_returns_empty():
    assert _flow.extract_answer_text("<html></html>", container_sel="div.nope") == ""


def test_is_logged_in_html_true_when_composer_present():
    html = '<html><body><textarea id="chat-input"></textarea></body></html>'
    assert _flow.is_logged_in_html(html, logged_in_sel="textarea#chat-input") is True


def test_is_logged_in_html_false_when_logged_out_marker_present():
    html = '<html><body><textarea></textarea><button class="login-btn">登录</button></body></html>'
    assert _flow.is_logged_in_html(
        html, logged_in_sel="textarea", logged_out_sel="button.login-btn") is False


def test_is_logged_in_html_false_when_composer_absent():
    assert _flow.is_logged_in_html("<html></html>", logged_in_sel="textarea") is False
```

- [ ] **Step 3: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_flow.py -v`
Expected: FAIL — `ModuleNotFoundError: ..rpa._flow` / `AttributeError`.

- [ ] **Step 4: 实现 `_flow.py` 纯函数**

`csm_core/monitor/geo/providers/rpa/_flow.py`：
```python
"""RPA 交互原语 + 纯 HTML 解析（站点无关，选择器作参数传入）。

DOM 读取拆「纯函数（吃 HTML 串，bs4，CI fixture 可测）+ 薄 page 包装」。
⚠ 传给纯函数的选择器（container_sel/logged_in_sel/logged_out_sel）必须是
合法 CSS（bs4 .select），不能用 Playwright :has-text 伪类。
"""
from __future__ import annotations
import logging
import time
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import Citation

logger = logging.getLogger(__name__)


# ── 纯解析（吃 HTML 串）─────────────────────────────────────────────
def extract_citations(html: str, *, container_sel: str | None = None,
                      exclude_hosts: tuple[str, ...] = ()) -> list[Citation]:
    """抽外链引用：容器内所有 http(s) <a>，title=锚文本，按 url 去重，
    排除 exclude_hosts（自家域名/导航）。container_sel=None 时扫整页。"""
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.select_one(container_sel) if container_sel else soup
    if root is None:
        return []
    seen: set[str] = set()
    out: list[Citation] = []
    for a in root.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        host = (urlparse(href).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in exclude_hosts):
            continue
        if href in seen:
            continue
        seen.add(href)
        title = " ".join(a.get_text(" ", strip=True).split())
        out.append(Citation(url=href, title=title))
    return out


def extract_answer_text(html: str, *, container_sel: str | None = None) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.select_one(container_sel) if container_sel else soup
    if root is None:
        return ""
    return " ".join(root.get_text(" ", strip=True).split())


def is_logged_in_html(html: str, *, logged_in_sel: str,
                      logged_out_sel: str | None = None) -> bool:
    """logged_in_sel 命中（如 composer 存在）且 logged_out_sel（若给）不命中 → True。"""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.select_one(logged_in_sel) is None:
        return False
    if logged_out_sel and soup.select_one(logged_out_sel) is not None:
        return False
    return True
```

- [ ] **Step 5: 跑绿**

Run: `pytest tests/core/monitor/geo/test_rpa_flow.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/__init__.py csm_core/monitor/geo/providers/rpa/_flow.py tests/core/monitor/geo/test_rpa_flow.py
git commit -m "feat(geo-rpa): _flow 纯 HTML 解析（引用抽取/正文/登录态判定）"
```

---

## Task 2: `_flow` page 交互原语（含流式等待 + cancel）

**Files:**
- Modify: `csm_core/monitor/geo/providers/rpa/_flow.py`（追加 page 原语）
- Test: `tests/core/monitor/geo/test_rpa_flow.py`（追加 FakePage 测试）

- [ ] **Step 1: 追加失败测试**

在 `tests/core/monitor/geo/test_rpa_flow.py` 末尾追加：
```python
import threading
import pytest


class _FakePage:
    """脚本化 page：content() 依次返回 _contents 序列（末值定格），
    query_selector 按 selector→对象表返回。"""
    def __init__(self, contents, selectors=None):
        self._contents = list(contents)
        self._selectors = selectors or {}
        self.filled = None
        self.clicked = []
        self.pressed = []

    def content(self):
        return self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]

    def query_selector(self, sel):
        v = self._selectors.get(sel)
        return v() if callable(v) else v

    def fill(self, sel, text):
        self.filled = (sel, text)

    def click(self, sel):
        self.clicked.append(sel)

    def press(self, sel, key):
        self.pressed.append((sel, key))


class _FakeEl:
    def __init__(self, *, enabled=True, attrs=None):
        self._enabled = enabled
        self._attrs = attrs or {}
    def is_enabled(self):
        return self._enabled
    def get_attribute(self, name):
        return self._attrs.get(name)
    def click(self):
        self._attrs["__clicked"] = True


def test_submit_query_fills_and_clicks_send():
    page = _FakePage(["<html></html>"])
    _flow.submit_query(page, composer_sel="textarea", send_sel="button.send", text="k")
    assert page.filled == ("textarea", "k")
    assert page.clicked == ["button.send"]


def test_submit_query_presses_enter_when_no_send_sel():
    page = _FakePage(["<html></html>"])
    _flow.submit_query(page, composer_sel="textarea", send_sel=None, text="k")
    assert page.pressed == [("textarea", "Enter")]


def test_ensure_web_toggle_clicks_when_off():
    el = _FakeEl(attrs={"aria-pressed": "false"})
    page = _FakePage(["<html></html>"], {"#web": el})
    _flow.ensure_web_toggle(page, toggle_sel="#web", want_on=True)
    assert el._attrs.get("__clicked") is True


def test_ensure_web_toggle_noop_when_already_on():
    el = _FakeEl(attrs={"aria-pressed": "true"})
    page = _FakePage(["<html></html>"], {"#web": el})
    _flow.ensure_web_toggle(page, toggle_sel="#web", want_on=True)
    assert el._attrs.get("__clicked") is None


def test_ensure_web_toggle_missing_toggle_is_ignored():
    page = _FakePage(["<html></html>"], {})
    _flow.ensure_web_toggle(page, toggle_sel="#nope", want_on=True)  # 不抛


def test_detect_login_uses_page_content():
    page = _FakePage(['<textarea id="c"></textarea>'])
    assert _flow.detect_login(page, logged_in_sel="textarea#c") is True


def test_wait_stream_done_returns_when_done_and_quiet():
    # 前两次 generating 在场→未完成；之后 generating 消失 + content 稳定→完成
    contents = ["<a>", "<ab>", "<abc>", "<abc>", "<abc>"]
    gen = iter([_FakeEl(), _FakeEl(), None, None, None, None, None, None])
    page = _FakePage(contents, {"#gen": lambda: next(gen, None)})
    _flow.wait_stream_done(
        page, done_predicate=lambda: page.query_selector("#gen") is None,
        idle_ms=1, timeout_s=5, poll_ms=1)


def test_wait_stream_done_timeout_raises():
    page = _FakePage(["<a>"], {})
    with pytest.raises(TimeoutError):
        _flow.wait_stream_done(page, done_predicate=lambda: False,
                               idle_ms=1, timeout_s=0.2, poll_ms=10)


def test_wait_stream_done_honors_cancel_token():
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        _CancelledFetch = RuntimeError
    tok = threading.Event(); tok.set()
    page = _FakePage(["<a>"], {})
    with pytest.raises(_CancelledFetch):
        _flow.wait_stream_done(page, done_predicate=lambda: False,
                               idle_ms=1, timeout_s=5, poll_ms=10, cancel_token=tok)
```

- [ ] **Step 2: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_flow.py -v -k "submit or toggle or detect_login or wait_stream"`
Expected: FAIL — `AttributeError: module ... has no attribute 'submit_query'`.

- [ ] **Step 3: 追加 page 原语到 `_flow.py`**

在 `_flow.py` 末尾追加：
```python
# ── page 包装（薄）─────────────────────────────────────────────────
def detect_login(page: Any, *, logged_in_sel: str,
                 logged_out_sel: str | None = None) -> bool:
    try:
        html = page.content()
    except Exception as e:
        logger.warning("detect_login page.content() raised: %s", e)
        return False
    return is_logged_in_html(html, logged_in_sel=logged_in_sel, logged_out_sel=logged_out_sel)


def submit_query(page: Any, *, composer_sel: str, send_sel: str | None, text: str) -> None:
    page.fill(composer_sel, text)
    if send_sel:
        page.click(send_sel)
    else:
        page.press(composer_sel, "Enter")


def ensure_web_toggle(page: Any, *, toggle_sel: str, want_on: bool = True,
                      on_attr: str = "aria-pressed", on_value: str = "true") -> None:
    """开/关联网开关。toggle 不存在 → 忽略（部分站默认联网/无显式开关）。"""
    el = page.query_selector(toggle_sel)
    if el is None:
        logger.info("ensure_web_toggle: %s not found (treat as default-on)", toggle_sel)
        return
    cur_on = (el.get_attribute(on_attr) or "").lower() == on_value.lower()
    if cur_on != want_on:
        el.click()


def wait_stream_done(page: Any, *, done_predicate: Callable[[], bool],
                     idle_ms: int = 1500, timeout_s: float = 90.0,
                     poll_ms: int = 500,
                     cancel_token: "Any | None" = None) -> None:
    """轮询直到 done_predicate() 为真且 page.content() 长度静默 idle_ms。
    超 timeout_s 抛 TimeoutError；每轮 maybe_cancel(cancel_token)（取消即抛）。"""
    deadline = time.monotonic() + timeout_s
    stable_since: float | None = None
    last_len = -1
    while True:
        maybe_cancel(cancel_token)
        if time.monotonic() > deadline:
            raise TimeoutError(f"wait_stream_done exceeded {timeout_s}s")
        try:
            done = bool(done_predicate())
        except Exception as e:
            logger.debug("done_predicate raised: %s", e)
            done = False
        try:
            cur_len = len(page.content())
        except Exception:
            cur_len = last_len
        quiet = cur_len == last_len
        last_len = cur_len
        if done and quiet:
            if stable_since is None:
                stable_since = time.monotonic()
            elif (time.monotonic() - stable_since) * 1000 >= idle_ms:
                return
        else:
            stable_since = None
        time.sleep(poll_ms / 1000.0)
```

- [ ] **Step 4: 跑绿**

Run: `pytest tests/core/monitor/geo/test_rpa_flow.py -v`
Expected: 全部 passed（Task1 的 7 + 本 Task 9）。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/_flow.py tests/core/monitor/geo/test_rpa_flow.py
git commit -m "feat(geo-rpa): _flow page 原语（提交/联网开关/流式等待+cancel/登录探测）"
```

---

## Task 3: `sites.py` —— 逐站选择器常量（DeepSeek 起）

**Files:**
- Create: `csm_core/monitor/geo/providers/rpa/sites.py`
- Test: `tests/core/monitor/geo/test_rpa_flow.py`（追加 SITES 合法性测试）

- [ ] **Step 1: 写失败测试（SITES 结构 + CSS 合法性）**

追加到 `tests/core/monitor/geo/test_rpa_flow.py`：
```python
def test_sites_deepseek_present_and_css_selectors_valid():
    from bs4 import BeautifulSoup
    from csm_core.monitor.geo.providers.rpa.sites import SITES, SiteSpec
    spec = SITES["deepseek"]
    assert isinstance(spec, SiteSpec)
    assert spec.url.startswith("https://")
    # 传给 bs4 的选择器必须是合法 CSS（否则 .select 抛 SelectorSyntaxError）
    soup = BeautifulSoup("<html></html>", "html.parser")
    for css in [spec.logged_in_sel, spec.answer_sel, spec.citation_sel]:
        soup.select(css)  # 不抛即合法
    if spec.logged_out_sel:
        soup.select(spec.logged_out_sel)
```

- [ ] **Step 2: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_flow.py::test_sites_deepseek_present_and_css_selectors_valid -v`
Expected: FAIL — `ModuleNotFoundError: ..rpa.sites`.

- [ ] **Step 3: 实现 `sites.py`**

`csm_core/monitor/geo/providers/rpa/sites.py`：
```python
"""每站 RPA 配置（URL + 选择器）—— 脆弱的逐站常量集中一处。

线上改版/选择器漂移 → 改这里 + 重抓 fixture/重新校准（不动 provider 逻辑）。
⚠ 区分两类选择器（见 _flow 顶注）：
- 纯函数用（bs4，必须合法 CSS）：answer_sel / citation_sel / logged_in_sel / logged_out_sel
- page 端用（可 Playwright 语法）：composer_sel / send_sel / web_toggle_sel / generating_sel

⚠ 下列选择器为初始最佳猜测，**必须用 Task 5/9/10 的人工 e2e 校准**（在原生
测试窗登录后 dump page.content() 比对真实 DOM）。校准前 CI 只跑 provider
错误路径（不依赖真选择器），真站抓取靠人工验收。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSpec:
    platform: str
    url: str
    composer_sel: str
    send_sel: str | None          # None → 按 Enter 提交
    web_toggle_sel: str | None    # None → 默认联网/无开关
    generating_sel: str | None    # 生成中在场的元素（如停止按钮）；None → 退化为 send 可点
    answer_sel: str               # 回答容器（抓正文，CSS）
    citation_sel: str             # 引用容器（抓来源链接，CSS；常与 answer_sel 同）
    logged_in_sel: str            # 登录态正向标志（CSS，如 composer 存在）
    logged_out_sel: str | None    # 未登录标志（CSS，如登录按钮稳定 class；命中=未登录）
    exclude_hosts: tuple[str, ...] = ()


SITES: dict[str, SiteSpec] = {
    "deepseek": SiteSpec(
        platform="deepseek",
        url="https://chat.deepseek.com/",
        composer_sel="textarea#chat-input, textarea",
        send_sel="div[role='button'][aria-label*='发送'], button[type='submit']",
        web_toggle_sel="div[role='button']:has-text('联网搜索')",  # page 端，允许 :has-text
        generating_sel="div[role='button'][aria-label*='停止']",    # page 端
        answer_sel="div.ds-markdown",                               # CSS，校准
        citation_sel="div.ds-markdown",                             # CSS，校准
        logged_in_sel="textarea",                                   # CSS
        logged_out_sel=None,                                        # 校准时填稳定登录按钮 class
        exclude_hosts=("deepseek.com",),
    ),
    # kimi（Task 9）/ yuanbao（Task 10）在各自 Task 加入此 dict。
}
```

- [ ] **Step 4: 跑绿**

Run: `pytest tests/core/monitor/geo/test_rpa_flow.py -v`
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/sites.py tests/core/monitor/geo/test_rpa_flow.py
git commit -m "feat(geo-rpa): sites.py 逐站选择器常量（DeepSeek，待 e2e 校准）"
```

---

## Task 4: `_session.py` —— 持久档会话 + 登录窗 + 登录态查询

**Files:**
- Create: `csm_core/monitor/geo/providers/rpa/_session.py`
- Test: `tests/core/monitor/geo/test_rpa_session.py`

说明：`rpa_page` 复用 `mining_browser.launched_page`（持久档 `browser_profiles/geo_<platform>/`；其 monitor-cookie 注入对 `geo_*` 平台无操作——不在 `_MONITOR_CRED_TYPE`——故 geo 登录态独立）。`open_login`/`login_status` 自行 launch（镜像 `baidu_login`，DOM marker 判登录，headless 用 `executable_path=pw.chromium.executable_path`）。

- [ ] **Step 1: 写失败测试**

`tests/core/monitor/geo/test_rpa_session.py`：
```python
import contextlib
import csm_core.monitor.geo.providers.rpa._session as sess


def test_rpa_page_wraps_launched_page_with_geo_prefix(monkeypatch):
    seen = {}

    @contextlib.contextmanager
    def fake_launched(platform, *, headless=False):
        seen["platform"] = platform
        seen["headless"] = headless
        yield "PAGE"

    monkeypatch.setattr(sess, "launched_page", fake_launched)
    with sess.rpa_page("deepseek", headless=True) as p:
        assert p == "PAGE"
    assert seen == {"platform": "geo_deepseek", "headless": True}


def test_login_status_unknown_platform_returns_false():
    out = sess.login_status("nope")
    assert out["logged_in"] is False


def test_open_login_unknown_platform_returns_error():
    out = sess.open_login("nope")
    assert out["status"] == "error"


class _Ctx:
    def __init__(self, html):
        self._html = html
        self.closed = False
        self._page = _Pg(html)
    @property
    def pages(self):
        return [self._page]
    def new_page(self):
        return self._page
    def on(self, *a, **k):
        pass
    def close(self):
        self.closed = True


class _Pg:
    def __init__(self, html):
        self._html = html
    def goto(self, *a, **k):
        pass
    def wait_for_timeout(self, *a, **k):
        pass
    def bring_to_front(self):
        pass
    def content(self):
        return self._html


class _PW:
    def __init__(self, html):
        self._html = html
        self.chromium = self
        self.executable_path = "/x/chromium"
        self.stopped = False
    def start(self):
        return self
    def launch_persistent_context(self, **k):
        return _Ctx(self._html)
    def stop(self):
        self.stopped = True


def _patch_pw(monkeypatch, html):
    monkeypatch.setattr(sess, "ensure_browsers_path", lambda: None)
    monkeypatch.setattr(sess, "_profile_dir_for", lambda p: __import__("pathlib").Path("/tmp") / p)
    import types
    fake_mod = types.SimpleNamespace(sync_playwright=lambda: _PW(html))
    monkeypatch.setitem(__import__("sys").modules, "patchright.sync_api", fake_mod)


def test_login_status_logged_in_true(monkeypatch):
    _patch_pw(monkeypatch, '<textarea id="chat-input"></textarea>')
    out = sess.login_status("deepseek")
    assert out["logged_in"] is True


def test_login_status_logged_out_false(monkeypatch):
    _patch_pw(monkeypatch, "<html><body>请登录</body></html>")
    out = sess.login_status("deepseek")
    assert out["logged_in"] is False


def test_open_login_success_when_marker_present(monkeypatch):
    _patch_pw(monkeypatch, '<textarea id="chat-input"></textarea>')
    out = sess.open_login("deepseek", timeout_s=2)
    assert out["status"] == "success"
```

- [ ] **Step 2: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_session.py -v`
Expected: FAIL — `ModuleNotFoundError: ..rpa._session`.

- [ ] **Step 3: 实现 `_session.py`**

`csm_core/monitor/geo/providers/rpa/_session.py`：
```python
"""GEO RPA 持久档会话 + 登录管理。

- rpa_page(platform): 采集用——开持久档页面、用完关（复用 mining_browser.launched_page）。
- open_login(platform): 有头窗让用户登录，轮询 DOM 登录态。
- login_status(platform): 无头快查登录态。
profile 落 browser_profiles/geo_<platform>/，与 mining/baidu 隔离。
"""
from __future__ import annotations
import contextlib
import logging
import time
from typing import Any, Iterator

from csm_core.browser_infra.mining_browser import launched_page, _profile_dir_for
from csm_core.browser_infra.patchright_pool import ensure_browsers_path
from csm_core.monitor.geo.providers.rpa._flow import is_logged_in_html
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 2000


@contextlib.contextmanager
def rpa_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """采集用持久档页面。geo_ 前缀隔离命名空间；monitor-cookie 注入对 geo_* 无操作。"""
    with launched_page(f"geo_{platform}", headless=headless) as page:
        yield page


def login_status(platform: str) -> dict[str, Any]:
    """无头快查登录态。返回 {"logged_in": bool}；任何失败降级 False。"""
    spec = SITES.get(platform)
    if spec is None:
        return {"logged_in": False, "error": f"未知 RPA 平台: {platform}"}
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        return {"logged_in": False, "error": "patchright 未安装"}
    ensure_browsers_path()
    user_data_dir = str(_profile_dir_for(f"geo_{platform}"))
    pw = None
    context = None
    try:
        pw = sync_playwright().start()
        # headless 必须用完整 Chromium 的 executable_path（同 baidu_login）——
        # 否则 patchright 找 chrome-headless-shell（未随包），启动即抛。
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=True,
            executable_path=pw.chromium.executable_path,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        html = page.content()
        logged_in = is_logged_in_html(
            html, logged_in_sel=spec.logged_in_sel, logged_out_sel=spec.logged_out_sel)
        logger.info("[geo-rpa][%s] login-status logged_in=%s", platform, logged_in)
        return {"logged_in": logged_in}
    except Exception as e:
        logger.warning("[geo-rpa][%s] login_status raised: %s", platform, e)
        return {"logged_in": False}
    finally:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()


def open_login(platform: str, *, timeout_s: int = 300) -> dict[str, Any]:
    """有头窗让用户登录，轮询 DOM 登录态。
    返回 {"status": "success"|"cancelled"|"timeout"|"error"}。持久档自动存 cookie。"""
    spec = SITES.get(platform)
    if spec is None:
        return {"status": "error", "error": f"未知 RPA 平台: {platform}"}
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "error": "patchright 未安装"}
    ensure_browsers_path()
    user_data_dir = str(_profile_dir_for(f"geo_{platform}"))
    pw = None
    context = None
    try:
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1100,820"],
            viewport={"width": 1100, "height": 820},
        )
        page = context.pages[0] if context.pages else context.new_page()
        state = {"closed": False}
        with contextlib.suppress(Exception):
            context.on("close", lambda *_: state.update(closed=True))
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
        with contextlib.suppress(Exception):
            page.bring_to_front()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if state["closed"]:
                return {"status": "cancelled"}
            try:
                html = page.content()
            except Exception:
                return {"status": "cancelled"}  # context 没了 = 用户关窗
            if is_logged_in_html(html, logged_in_sel=spec.logged_in_sel,
                                 logged_out_sel=spec.logged_out_sel):
                page.wait_for_timeout(1500)  # 等其余 cookie 落盘
                logger.info("[geo-rpa][%s] login success", platform)
                return {"status": "success"}
            page.wait_for_timeout(_POLL_INTERVAL_MS)
        return {"status": "timeout"}
    except Exception as e:
        logger.warning("[geo-rpa][%s] open_login raised: %s", platform, e)
        return {"status": "error", "error": str(e)}
    finally:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()
```

- [ ] **Step 4: 跑绿**

Run: `pytest tests/core/monitor/geo/test_rpa_session.py -v`
Expected: 7 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/_session.py tests/core/monitor/geo/test_rpa_session.py
git commit -m "feat(geo-rpa): _session 持久档会话 + 有头登录窗 + 无头登录态查询"
```

---

## Task 5: DeepSeek provider + 注册 + 打包 hiddenimport

**Files:**
- Create: `csm_core/monitor/geo/providers/rpa/deepseek.py`
- Modify: `csm_core/monitor/geo/providers/base.py:22-42`（加 deepseek 分支）
- Modify: `sidecar/csm-sidecar.spec:142`（加 rpa hiddenimports）
- Test: `tests/core/monitor/geo/test_rpa_providers.py`
- Modify: `tests/core/monitor/geo/test_registration.py`

- [ ] **Step 1: 写失败测试（provider 错误路径，monkeypatch 假会话）**

`tests/core/monitor/geo/test_rpa_providers.py`：
```python
import contextlib
import threading
import pytest
import csm_core.monitor.geo.providers.rpa.deepseek as ds


class _FakePage:
    def __init__(self, html, *, raise_on_wait=None):
        self._html = html
        self._raise_on_wait = raise_on_wait
    def goto(self, *a, **k):
        pass
    def wait_for_timeout(self, *a, **k):
        pass
    def content(self):
        return self._html
    def query_selector(self, sel):
        return None
    def fill(self, *a, **k):
        pass
    def click(self, *a, **k):
        pass
    def press(self, *a, **k):
        pass


def _patch_session(monkeypatch, page, *, wait=None):
    @contextlib.contextmanager
    def fake_rpa_page(platform, *, headless=False):
        yield page
    monkeypatch.setattr(ds, "rpa_page", fake_rpa_page)
    if wait is not None:
        monkeypatch.setattr(ds._flow, "wait_stream_done", wait)


def test_deepseek_blocked_when_not_logged_in(monkeypatch):
    _patch_session(monkeypatch, _FakePage("<html><body>请登录</body></html>"))
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "blocked"
    assert "登录" in ans.error


def test_deepseek_ok_when_logged_in_and_answer_present(monkeypatch):
    html = ('<textarea id="chat-input"></textarea>'
            '<div class="ds-markdown">推荐小鹏G6 '
            '<a href="https://zhuanlan.zhihu.com/p/9">知乎</a></div>')
    _patch_session(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
    assert ans.citations[0].url == "https://zhuanlan.zhihu.com/p/9"


def test_deepseek_empty_when_logged_in_but_no_answer(monkeypatch):
    html = '<textarea id="chat-input"></textarea><div class="ds-markdown"></div>'
    _patch_session(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "empty"


def test_deepseek_timeout_becomes_error(monkeypatch):
    html = '<textarea id="chat-input"></textarea>'
    def _boom(*a, **k):
        raise TimeoutError("stream too slow")
    _patch_session(monkeypatch, _FakePage(html), wait=_boom)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "error"
    assert "slow" in ans.error or "timeout" in ans.error.lower()


def test_deepseek_query_never_raises(monkeypatch):
    # rpa_page 本身抛 → provider 兜成 error，不冒泡
    @contextlib.contextmanager
    def boom_page(platform, *, headless=False):
        raise RuntimeError("browser launch failed")
        yield  # pragma: no cover
    monkeypatch.setattr(ds, "rpa_page", boom_page)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "error"
```

- [ ] **Step 2: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: ..rpa.deepseek`.

- [ ] **Step 3: 实现 `deepseek.py`**

`csm_core/monitor/geo/providers/rpa/deepseek.py`：
```python
"""DeepSeek RPA provider —— 驱动 chat.deepseek.com 网页采集联网回答+来源。

错误纪律：未登录→blocked；超时/浏览器异常→error；空回答→empty。provider
绝不让异常冒泡（adapter 虽也兜，但 provider 自身要稳）。选择器全在 sites.py，
线上漂移改那里。
"""
from __future__ import annotations
import logging
import threading

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _flow
from csm_core.monitor.geo.providers.rpa._session import rpa_page
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)
_SPEC = SITES["deepseek"]


class DeepSeekProvider:
    platform = "deepseek"
    mode = "rpa"

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        spec = _SPEC
        try:
            with rpa_page(self.platform, headless=False) as page:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                if not _flow.detect_login(page, logged_in_sel=spec.logged_in_sel,
                                          logged_out_sel=spec.logged_out_sel):
                    return GeoAnswer(platform=self.platform, keyword=keyword,
                                     status="blocked", error="DeepSeek 未登录，请在设置中登录")
                if web_search and spec.web_toggle_sel:
                    _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
                _flow.submit_query(page, composer_sel=spec.composer_sel,
                                   send_sel=spec.send_sel, text=keyword)

                def _done() -> bool:
                    if spec.generating_sel:
                        return page.query_selector(spec.generating_sel) is None
                    el = page.query_selector(spec.send_sel) if spec.send_sel else None
                    return el is not None and el.is_enabled()

                _flow.wait_stream_done(page, done_predicate=_done, idle_ms=1500,
                                       timeout_s=120.0, cancel_token=cancel_token)
                html = page.content()
            answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
            cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                            exclude_hosts=spec.exclude_hosts)
            logger.info("[geo-rpa][deepseek] kw=%s answer_len=%d cite_n=%d",
                        keyword, len(answer), len(cites))
            return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=answer,
                             citations=cites, status="ok" if answer else "empty",
                             raw={"html_len": len(html), "cite_n": len(cites)})
        except Exception as e:
            logger.exception("[geo-rpa][deepseek] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error=str(e))
```

- [ ] **Step 4: 跑绿（provider 测试）**

Run: `pytest tests/core/monitor/geo/test_rpa_providers.py -v`
Expected: 5 passed。

- [ ] **Step 5: 注册 get_provider（写测试先）**

改 `tests/core/monitor/geo/test_registration.py` —— 追加：
```python
def test_get_provider_deepseek_is_rpa():
    from csm_core.monitor.geo.providers.base import get_provider
    p = get_provider("deepseek")
    assert p.platform == "deepseek" and p.mode == "rpa"
```
Run: `pytest tests/core/monitor/geo/test_registration.py -v` → FAIL（`未知 GEO 平台: deepseek`）。

改 `csm_core/monitor/geo/providers/base.py`：在 `doubao` 分支后、`raise` 前插入：
```python
    if platform == "deepseek":
        try:
            from .rpa.deepseek import DeepSeekProvider
        except ImportError as e:
            raise GeoProviderError(f"deepseek provider 未就绪: {e}") from e
        return DeepSeekProvider()
```
Run: `pytest tests/core/monitor/geo/test_registration.py -v` → PASS。

- [ ] **Step 6: 打包 hiddenimport**

改 `sidecar/csm-sidecar.spec`，在第 142 行 `"csm_core.monitor.geo.providers.api_doubao",` 后插入：
```python
    "csm_core.monitor.geo.providers.rpa",
    "csm_core.monitor.geo.providers.rpa._flow",
    "csm_core.monitor.geo.providers.rpa._session",
    "csm_core.monitor.geo.providers.rpa.sites",
    "csm_core.monitor.geo.providers.rpa.deepseek",
```

- [ ] **Step 7: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/deepseek.py csm_core/monitor/geo/providers/base.py sidecar/csm-sidecar.spec tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_registration.py
git commit -m "feat(geo-rpa): DeepSeek provider + get_provider 注册 + spec hiddenimport"
```

---

## Task 6: 登录路由（后端）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`（加 2 路由，紧跟 baidu login-status 之后 ~428 行）
- Test: `sidecar/tests/test_monitor_routes.py`

- [ ] **Step 1: 写失败测试**

追加到 `sidecar/tests/test_monitor_routes.py`：
```python
def test_geo_rpa_login_status_ok(client: TestClient, monkeypatch):
    import csm_core.monitor.geo.providers.rpa._session as sess
    monkeypatch.setattr(sess, "login_status", lambda p: {"logged_in": True})
    r = client.get("/api/monitor/geo/rpa/deepseek/login-status")
    assert r.status_code == 200
    assert r.json()["logged_in"] is True


def test_geo_rpa_login_status_unknown_platform_404(client: TestClient):
    r = client.get("/api/monitor/geo/rpa/nope/login-status")
    assert r.status_code == 404


def test_geo_rpa_login_status_soft_fallback(client: TestClient, monkeypatch):
    import csm_core.monitor.geo.providers.rpa._session as sess
    def _boom(p):
        raise RuntimeError("profile corrupt")
    monkeypatch.setattr(sess, "login_status", _boom)
    r = client.get("/api/monitor/geo/rpa/deepseek/login-status")
    assert r.status_code == 200 and r.json()["logged_in"] is False


def test_geo_rpa_login_open(client: TestClient, monkeypatch):
    import csm_core.monitor.geo.providers.rpa._session as sess
    monkeypatch.setattr(sess, "open_login", lambda p, **k: {"status": "success"})
    r = client.post("/api/monitor/geo/rpa/deepseek/login")
    assert r.status_code == 200 and r.json()["status"] == "success"


def test_geo_rpa_login_open_unknown_platform_404(client: TestClient):
    r = client.post("/api/monitor/geo/rpa/nope/login")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑红**

Run: `pytest sidecar/tests/test_monitor_routes.py -v -k geo_rpa`
Expected: FAIL — 404（路由不存在）对 status_code==200 的用例失败。

- [ ] **Step 3: 实现路由**

在 `sidecar/csm_sidecar/routes/monitor.py` 的 `baidu_login_status`（~428 行）之后插入：
```python
# ── GEO RPA 登录（DeepSeek/Kimi/元宝 真浏览器持久档登录态）─────────────
_GEO_RPA_PLATFORMS = {"deepseek", "kimi", "yuanbao"}


@router.post("/api/monitor/geo/rpa/{platform}/login")
async def geo_rpa_login_open(platform: str) -> dict[str, Any]:
    """开有头窗让用户登录某 RPA 平台。持久档落 browser_profiles/geo_<platform>/。
    sync patchright 不能在 asyncio loop 里跑 → to_thread。"""
    import asyncio
    if platform not in _GEO_RPA_PLATFORMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"未知 RPA 平台: {platform}")
    from csm_core.monitor.geo.providers.rpa import _session
    return await asyncio.to_thread(_session.open_login, platform)


@router.get("/api/monitor/geo/rpa/{platform}/login-status")
async def geo_rpa_login_status(platform: str) -> dict[str, Any]:
    """无头快查登录态。失败降级 {logged_in: False}，不 5xx。"""
    import asyncio
    if platform not in _GEO_RPA_PLATFORMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"未知 RPA 平台: {platform}")
    from csm_core.monitor.geo.providers.rpa import _session
    try:
        return await asyncio.to_thread(_session.login_status, platform)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("geo rpa login-status[%s] failed: %s", platform, e)
        return {"logged_in": False}
```

注：路由内 `from ... import _session` 后调 `_session.open_login` / `_session.login_status`（属性访问），所以测试 monkeypatch `_session.login_status` 能生效。

- [ ] **Step 4: 跑绿**

Run: `pytest sidecar/tests/test_monitor_routes.py -v -k geo_rpa`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_monitor_routes.py
git commit -m "feat(geo-rpa): 后端 geo rpa 登录/登录态路由（镜像 baidu，to_thread）"
```

---

## Task 7: 前端 —— 平台选择器 + 设置页 RPA 登录分组

**Files:**
- Modify: `frontend/src/utils/monitor-types.ts`（`GEO_PLATFORMS` 加 deepseek + `mode`）
- Create: `frontend/src/utils/__tests__/monitor-types.spec.ts`
- Modify: `frontend/src/views/SettingsView.vue`（RPA 登录分组）

（Kimi/元宝 在 Task 9/10 加进 `GEO_PLATFORMS`；本 Task 仅 deepseek 打通前端。）

- [ ] **Step 1: 写失败测试（vitest）**

`frontend/src/utils/__tests__/monitor-types.spec.ts`：
```ts
import { describe, it, expect } from "vitest";
import { GEO_PLATFORMS } from "../monitor-types";

describe("GEO_PLATFORMS", () => {
  it("includes DeepSeek as an rpa platform", () => {
    const ds = GEO_PLATFORMS.find((p) => p.value === "deepseek");
    expect(ds).toBeTruthy();
    expect(ds?.mode).toBe("rpa");
  });
  it("keeps api platforms tagged api", () => {
    expect(GEO_PLATFORMS.find((p) => p.value === "tongyi")?.mode).toBe("api");
  });
});
```

- [ ] **Step 2: 跑红**

Run（cwd=frontend）: `npm run test -- monitor-types`
Expected: FAIL — deepseek undefined / mode undefined。

- [ ] **Step 3: 改 `monitor-types.ts`**

把 `GEO_PLATFORMS` 块替换为：
```ts
export const GEO_PLATFORMS = [
  { value: "tongyi", label: "通义千问", mode: "api" },
  { value: "doubao", label: "豆包", mode: "api" },
  { value: "deepseek", label: "DeepSeek", mode: "rpa" },
] as const;
```

- [ ] **Step 4: 跑绿 + 类型检查**

Run（cwd=frontend）: `npm run test -- monitor-types` → PASS
Run（cwd=frontend）: `npx vue-tsc --noEmit` → 无新错误（若有消费 `GEO_PLATFORMS` 的地方因 `mode` 联合类型报错，按提示放宽为 `string`；新增字段是叠加，既有 `.value/.label` 不受影响）。

> 平台多选 UI（新增任务弹窗）若要给 `mode==="rpa"` 显示「需登录」提示：在渲染 `GEO_PLATFORMS` 的组件里加 `<span v-if="p.mode==='rpa'">需登录</span>`。定位渲染处：`git -C <wt> grep -n "GEO_PLATFORMS" frontend/src` 找到引用文件，按其模板结构加提示（非阻塞，可放 Task 11 一起 polish）。

- [ ] **Step 5: 设置页 RPA 登录分组**

在 `SettingsView.vue` `<script setup>` 内（紧跟 baidu 登录逻辑 ~726 行之后）加：
```ts
// AI 卡位 RPA 登录态（DeepSeek/Kimi/元宝 真浏览器持久档）
const RPA_PLATFORMS = [
  { value: "deepseek", label: "DeepSeek" },
  { value: "kimi", label: "Kimi" },
  { value: "yuanbao", label: "腾讯元宝" },
] as const;
const rpaLogin = reactive<Record<string, { logged_in: boolean; busy: boolean }>>({
  deepseek: { logged_in: false, busy: false },
  kimi: { logged_in: false, busy: false },
  yuanbao: { logged_in: false, busy: false },
});

async function refreshRpaLoginStatus(platform: string) {
  try {
    const r = await sidecar.client.get(`/api/monitor/geo/rpa/${platform}/login-status`);
    rpaLogin[platform].logged_in = !!r.data?.logged_in;
  } catch {
    rpaLogin[platform].logged_in = false;
  }
}

async function startRpaLogin(platform: string, label: string) {
  if (!(await confirmDialog(
    "会打开一个浏览器窗口，登录后 CSM 卡位采集任务自动用登录态访问。建议使用专用账号。",
    { title: `登录 ${label}`, okLabel: "登录", kind: "info" },
  ))) return;
  rpaLogin[platform].busy = true;
  try {
    const r = await sidecar.client.post(`/api/monitor/geo/rpa/${platform}/login`, null, { timeout: 360_000 });
    const status = r.data?.status;
    if (status === "success") toast.success(`${label} 登录成功`);
    else if (status === "cancelled") toast.info("登录已取消");
    else if (status === "timeout") toast.error("登录超时（窗口已关闭）");
    else toast.error(`登录失败：${r.data?.error ?? status}`);
  } catch (e: any) {
    toast.error(`登录失败：${e.response?.data?.detail ?? e.message ?? "未知错误"}`);
  } finally {
    rpaLogin[platform].busy = false;
    await refreshRpaLoginStatus(platform);
  }
}
```
并在 `onMounted`（或已有的初始刷新处，搜 `refreshBaiduLoginStatus(` 的调用点）追加：
```ts
  RPA_PLATFORMS.forEach((p) => refreshRpaLoginStatus(p.value));
```

在模板「百度关键词」分组（~1559 行 `<div class="mt-6 pt-5" ...>` 那块）之前或之后，加一个同构分组：
```html
            <div class="mt-6 pt-5" :style="{ borderTop: '1px solid var(--line)' }">
              <div class="mb-3 font-display text-[13px] font-semibold" :style="{ color: 'var(--ink)' }">
                AI 卡位 · RPA 登录
              </div>
              <SettingsRow
                v-for="p in RPA_PLATFORMS"
                :key="p.value"
                :label="p.label"
                hint="需登录后才能采集该平台的联网回答与来源。建议用专用账号。"
              >
                <div class="flex items-center gap-3">
                  <span
                    v-if="rpaLogin[p.value].logged_in"
                    class="text-[12px]" :style="{ color: 'var(--success, #16a34a)' }"
                  >已登录</span>
                  <span v-else class="text-[12px]" :style="{ color: 'var(--ink-3)' }">未登录</span>
                  <Btn variant="solid" small :disabled="rpaLogin[p.value].busy"
                       @click="startRpaLogin(p.value, p.label)">
                    <Icon name="user" :size="12" />
                    <span>{{ rpaLogin[p.value].logged_in ? "重新登录" : "登录" }}</span>
                  </Btn>
                </div>
              </SettingsRow>
            </div>
```

确认 `reactive` 已在 `SettingsView.vue` 的 vue import 里（搜 `from "vue"`；没有则补 `reactive`）。

- [ ] **Step 6: 类型检查 + 构建**

Run（cwd=frontend）: `npx vue-tsc --noEmit` → 无新错误。
（设置页交互留 Task 11 人工验收；此处只保证类型/构建过。）

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/monitor-types.ts frontend/src/utils/__tests__/monitor-types.spec.ts frontend/src/views/SettingsView.vue
git commit -m "feat(geo-rpa): 前端 GEO_PLATFORMS 加 DeepSeek + 设置页 RPA 登录分组"
```

---

## Task 8: adapter 透传 cancel_token + 串行化

**Files:**
- Modify: `csm_core/monitor/platforms/geo_query.py`（cancel_token 透传 + 模块级串行化）
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/monitor/geo/test_geo_query_adapter.py`：
```python
def test_run_cell_passes_cancel_token_to_provider(monkeypatch):
    import threading
    from csm_core.monitor.platforms import geo_query as gq

    seen = {}

    class _Prov:
        platform = "deepseek"; mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            seen["cancel_token"] = cancel_token
            from csm_core.monitor.geo.models import GeoAnswer
            return GeoAnswer(platform="deepseek", keyword=kw, answer_text="x", status="ok")

    monkeypatch.setattr(gq, "get_provider", lambda p: _Prov())
    monkeypatch.setattr(gq, "extract",
                        lambda ans, **k: __import__("csm_core.monitor.geo.models", fromlist=["GeoExtraction"]).GeoExtraction())
    tok = threading.Event()
    adapter = gq.GeoQueryAdapter()
    adapter._run_cell("kw", "deepseek", "Brand", [], True, object(), cancel_token=tok)
    assert seen["cancel_token"] is tok


def test_geo_query_configures_serial_concurrency():
    # 模块导入即把 geo_query 并发设为 1（slot 在 loop 里先于 fetch 获取）
    from csm_core.browser_infra import rate_limit
    from csm_core.monitor.platforms import geo_query  # noqa: F401  确保已导入
    assert rate_limit._max_concurrent.get("geo_query") == 1
```

- [ ] **Step 2: 跑红**

Run: `pytest tests/core/monitor/geo/test_geo_query_adapter.py -v -k "cancel_token or serial"`
Expected: FAIL — `_run_cell` 不接受 `cancel_token` / `_max_concurrent` 无 geo_query。

- [ ] **Step 3: 改 `geo_query.py`**

(a) 顶部 import 区（`from ..geo import storage as geo_storage` 之后）加：
```python
from ..rate_limit import configure_concurrency
```
(b) 文件末尾 `ADAPTER = GeoQueryAdapter()` 之后加（模块级，导入即生效——loop 在 `slot(task.type)` 取槽前 adapter 模块已注册导入）：
```python

# geo RPA 会开有头 Chrome：把 geo_query 并发设为 1，避免两次运行抢同一
# geo_<platform> 持久档 / 同时弹多窗。monitor_loop 用 slot(task.type) 取槽，
# 故必须在「取槽前」配置好——模块级（导入时）配置最稳，不走 baidu 的 in-fetch 懒配。
configure_concurrency("geo_query", 1)
```
(c) `_run_cell` 签名（第 141-149 行）加 `cancel_token`：
```python
    def _run_cell(
        self,
        keyword: str,
        platform: str,
        brand: str,
        aliases: list[str],
        web_search: bool,
        client: Any,
        cancel_token: "threading.Event | None" = None,
    ) -> GeoCell:
```
(d) `_run_cell` 内 provider 调用（第 152 行）传 token：
```python
            answer = provider.query(keyword, web_search=web_search, cancel_token=cancel_token)
```
(e) `fetch` 内调用处（第 90 行）传 token：
```python
            cell = self._run_cell(kw, plat, brand, aliases, web_search, client, cancel_token=cancel_token)
```

- [ ] **Step 4: 跑绿（含回归）**

Run: `pytest tests/core/monitor/geo/test_geo_query_adapter.py -v`
Expected: 全 passed。

回归检查 —— API provider 的 `query` 必须都接受 `cancel_token`（否则透传 TypeError）。确认：
```bash
git -C . grep -nE 'def query\(self, keyword' csm_core/monitor/geo/providers/api_tongyi.py csm_core/monitor/geo/providers/api_kimi.py csm_core/monitor/geo/providers/api_doubao.py
```
Expected: 三者签名都含 `cancel_token`（doubao 已确认有；tongyi/kimi 若缺，补 `, cancel_token: "threading.Event | None" = None` 到签名——base Protocol 已要求）。补完跑：
Run: `pytest tests/core/monitor/geo/test_providers.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/platforms/geo_query.py tests/core/monitor/geo/test_geo_query_adapter.py csm_core/monitor/geo/providers/api_tongyi.py csm_core/monitor/geo/providers/api_kimi.py
git commit -m "feat(geo-rpa): adapter 透传 cancel_token + geo_query 串行化(concurrency=1)"
```
（若 tongyi/kimi 签名无需改，从 add 列表去掉对应文件。）

---

## Task 9: Kimi RPA provider（API 版改指 RPA）

**Files:**
- Modify: `csm_core/monitor/geo/providers/rpa/sites.py`（加 kimi）
- Create: `csm_core/monitor/geo/providers/rpa/kimi.py`
- Modify: `csm_core/monitor/geo/providers/base.py`（kimi 分支 **改指** rpa.kimi）
- Modify: `sidecar/csm-sidecar.spec`（加 rpa.kimi）
- Modify: `frontend/src/utils/monitor-types.ts`（GEO_PLATFORMS 加回 kimi）
- Test: `tests/core/monitor/geo/test_rpa_providers.py`、`test_registration.py`

- [ ] **Step 1: sites.py 加 kimi**

在 `SITES` dict 里 `"deepseek": ...,` 之后加（选择器初始猜测，e2e 校准）：
```python
    "kimi": SiteSpec(
        platform="kimi",
        url="https://kimi.com/",
        composer_sel="div[contenteditable='true'], textarea",
        send_sel="div[role='button'][aria-label*='发送'], button[type='submit']",
        web_toggle_sel="div[role='button']:has-text('联网')",
        generating_sel="div[role='button'][aria-label*='停止']",
        answer_sel="div.markdown, div[class*='answer']",
        citation_sel="div.markdown, div[class*='answer']",
        logged_in_sel="div[contenteditable='true'], textarea",
        logged_out_sel=None,
        exclude_hosts=("kimi.com", "moonshot.cn"),
    ),
```

- [ ] **Step 2: 写失败测试（provider + 注册）**

追加到 `tests/core/monitor/geo/test_rpa_providers.py`（复用 Task5 的 `_FakePage`/`_patch_session` 思路，但 patch kimi 模块）：
```python
import csm_core.monitor.geo.providers.rpa.kimi as km


def _patch_km(monkeypatch, page, *, wait=None):
    import contextlib
    @contextlib.contextmanager
    def fake(platform, *, headless=False):
        yield page
    monkeypatch.setattr(km, "rpa_page", fake)
    if wait is not None:
        monkeypatch.setattr(km._flow, "wait_stream_done", wait)


def test_kimi_blocked_when_not_logged_in(monkeypatch):
    _patch_km(monkeypatch, _FakePage("<html><body>登录 Kimi</body></html>"))
    ans = km.KimiProvider().query("k", web_search=True)
    assert ans.status == "blocked"


def test_kimi_ok_when_answer_present(monkeypatch):
    html = ('<div contenteditable="true"></div>'
            '<div class="markdown">小鹏G6 不错 '
            '<a href="https://www.autohome.com.cn/a">汽车之家</a></div>')
    _patch_km(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = km.KimiProvider().query("k", web_search=True)
    assert ans.status == "ok" and ans.citations[0].url.startswith("https://www.autohome")
```
追加到 `tests/core/monitor/geo/test_registration.py`：
```python
def test_get_provider_kimi_is_rpa_now():
    from csm_core.monitor.geo.providers.base import get_provider
    p = get_provider("kimi")
    assert p.platform == "kimi" and p.mode == "rpa"  # 阶段3：API 版改指 RPA
```

- [ ] **Step 3: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_registration.py -v -k kimi`
Expected: FAIL — 无 `rpa.kimi` / get_provider("kimi") 仍是 api（mode=="api"）。

- [ ] **Step 4: 实现 `kimi.py`**

`csm_core/monitor/geo/providers/rpa/kimi.py`（与 deepseek 同构，仅 `platform`/`_SPEC` 不同；完整重写，勿 "同 DeepSeek"）：
```python
"""Kimi RPA provider —— 驱动 kimi.com 网页采集联网回答+来源。

阶段 2 确认 Moonshot API 的 $web_search 不回信源（annotations 恒 0），故 Kimi
改走 RPA。错误纪律同 DeepSeek：未登录→blocked；超时/异常→error；空→empty。
"""
from __future__ import annotations
import logging
import threading

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _flow
from csm_core.monitor.geo.providers.rpa._session import rpa_page
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)
_SPEC = SITES["kimi"]


class KimiProvider:
    platform = "kimi"
    mode = "rpa"

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        spec = _SPEC
        try:
            with rpa_page(self.platform, headless=False) as page:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                if not _flow.detect_login(page, logged_in_sel=spec.logged_in_sel,
                                          logged_out_sel=spec.logged_out_sel):
                    return GeoAnswer(platform=self.platform, keyword=keyword,
                                     status="blocked", error="Kimi 未登录，请在设置中登录")
                if web_search and spec.web_toggle_sel:
                    _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
                _flow.submit_query(page, composer_sel=spec.composer_sel,
                                   send_sel=spec.send_sel, text=keyword)

                def _done() -> bool:
                    if spec.generating_sel:
                        return page.query_selector(spec.generating_sel) is None
                    el = page.query_selector(spec.send_sel) if spec.send_sel else None
                    return el is not None and el.is_enabled()

                _flow.wait_stream_done(page, done_predicate=_done, idle_ms=1500,
                                       timeout_s=120.0, cancel_token=cancel_token)
                html = page.content()
            answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
            cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                            exclude_hosts=spec.exclude_hosts)
            logger.info("[geo-rpa][kimi] kw=%s answer_len=%d cite_n=%d",
                        keyword, len(answer), len(cites))
            return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=answer,
                             citations=cites, status="ok" if answer else "empty",
                             raw={"html_len": len(html), "cite_n": len(cites)})
        except Exception as e:
            logger.exception("[geo-rpa][kimi] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error=str(e))
```

- [ ] **Step 5: base.py kimi 分支改指 RPA**

把 `base.py` 的 kimi 分支（第 30-35 行）整体替换：
```python
    if platform == "kimi":
        # 阶段 3：Kimi 改走 RPA（API 版 annotations 恒 0 拿不到信源）。
        try:
            from .rpa.kimi import KimiProvider
        except ImportError as e:
            raise GeoProviderError(f"kimi(rpa) provider 未就绪: {e}") from e
        return KimiProvider()
```
并更新 `get_provider` docstring（第 23 行）为：
```python
    """返回 provider 实例（每次新建，provider 无状态）。
    API：tongyi / doubao；RPA：deepseek / kimi / yuanbao。"""
```
> 注：`api_kimi.py` 模块保留（其单测 `test_providers.py` 仍直接 import 它），只是 `get_provider('kimi')` 不再走它。

- [ ] **Step 6: spec hiddenimport + 前端 GEO_PLATFORMS 加回 kimi**

spec：第 5 行新增的 `"...rpa.deepseek",` 后加 `    "csm_core.monitor.geo.providers.rpa.kimi",`。
`monitor-types.ts`：`GEO_PLATFORMS` 在 deepseek 后加 `{ value: "kimi", label: "Kimi", mode: "rpa" },`。

- [ ] **Step 7: 跑绿**

Run: `pytest tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_registration.py tests/core/monitor/geo/test_providers.py -v`
Expected: 全 passed（含既有 api_kimi 直测仍绿）。
Run（cwd=frontend）: `npm run test -- monitor-types` → PASS。

- [ ] **Step 8: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/sites.py csm_core/monitor/geo/providers/rpa/kimi.py csm_core/monitor/geo/providers/base.py sidecar/csm-sidecar.spec frontend/src/utils/monitor-types.ts tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_registration.py
git commit -m "feat(geo-rpa): Kimi RPA provider + get_provider kimi 改指 rpa + GEO_PLATFORMS 加回"
```

---

## Task 10: 腾讯元宝 RPA provider（扫码登录）

**Files:**
- Modify: `csm_core/monitor/geo/providers/rpa/sites.py`（加 yuanbao）
- Create: `csm_core/monitor/geo/providers/rpa/yuanbao.py`
- Modify: `csm_core/monitor/geo/providers/base.py`（加 yuanbao 分支）
- Modify: `sidecar/csm-sidecar.spec`、`frontend/src/utils/monitor-types.ts`
- Test: `tests/core/monitor/geo/test_rpa_providers.py`、`test_registration.py`

- [ ] **Step 1: sites.py 加 yuanbao**

`SITES` 里 kimi 之后加：
```python
    "yuanbao": SiteSpec(
        platform="yuanbao",
        url="https://yuanbao.tencent.com/",
        composer_sel="div[contenteditable='true'], textarea",
        send_sel="div[role='button'][aria-label*='发送'], button[type='submit']",
        web_toggle_sel="div[role='button']:has-text('联网')",
        generating_sel="div[role='button'][aria-label*='停止']",
        answer_sel="div[class*='markdown'], div[class*='answer']",
        citation_sel="div[class*='markdown'], div[class*='answer']",
        logged_in_sel="div[contenteditable='true'], textarea",
        logged_out_sel=None,
        exclude_hosts=("yuanbao.tencent.com", "tencent.com"),
    ),
```

- [ ] **Step 2: 写失败测试**

追加到 `test_rpa_providers.py`：
```python
import csm_core.monitor.geo.providers.rpa.yuanbao as yb


def _patch_yb(monkeypatch, page, *, wait=None):
    import contextlib
    @contextlib.contextmanager
    def fake(platform, *, headless=False):
        yield page
    monkeypatch.setattr(yb, "rpa_page", fake)
    if wait is not None:
        monkeypatch.setattr(yb._flow, "wait_stream_done", wait)


def test_yuanbao_blocked_when_not_logged_in(monkeypatch):
    _patch_yb(monkeypatch, _FakePage("<html><body>扫码登录</body></html>"))
    ans = yb.YuanbaoProvider().query("k", web_search=True)
    assert ans.status == "blocked"


def test_yuanbao_ok_when_answer_present(monkeypatch):
    html = ('<div contenteditable="true"></div>'
            '<div class="markdown-body">小鹏G6 '
            '<a href="https://zhuanlan.zhihu.com/p/77">知乎</a></div>')
    _patch_yb(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = yb.YuanbaoProvider().query("k", web_search=True)
    assert ans.status == "ok" and ans.citations[0].url.endswith("/p/77")
```
追加到 `test_registration.py`：
```python
def test_get_provider_yuanbao_is_rpa():
    from csm_core.monitor.geo.providers.base import get_provider
    p = get_provider("yuanbao")
    assert p.platform == "yuanbao" and p.mode == "rpa"
```

- [ ] **Step 3: 跑红**

Run: `pytest tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_registration.py -v -k yuanbao`
Expected: FAIL — 无 `rpa.yuanbao`。

- [ ] **Step 4: 实现 `yuanbao.py`**

`csm_core/monitor/geo/providers/rpa/yuanbao.py`（与 deepseek 同构，完整重写）：
```python
"""腾讯元宝 RPA provider —— 驱动 yuanbao.tencent.com 网页采集联网回答+来源。

登录走 QQ/微信扫码（用户在有头窗扫码，持久档存会话）。错误纪律同 DeepSeek。
"""
from __future__ import annotations
import logging
import threading

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _flow
from csm_core.monitor.geo.providers.rpa._session import rpa_page
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)
_SPEC = SITES["yuanbao"]


class YuanbaoProvider:
    platform = "yuanbao"
    mode = "rpa"

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        spec = _SPEC
        try:
            with rpa_page(self.platform, headless=False) as page:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                if not _flow.detect_login(page, logged_in_sel=spec.logged_in_sel,
                                          logged_out_sel=spec.logged_out_sel):
                    return GeoAnswer(platform=self.platform, keyword=keyword,
                                     status="blocked", error="腾讯元宝 未登录，请在设置中扫码登录")
                if web_search and spec.web_toggle_sel:
                    _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
                _flow.submit_query(page, composer_sel=spec.composer_sel,
                                   send_sel=spec.send_sel, text=keyword)

                def _done() -> bool:
                    if spec.generating_sel:
                        return page.query_selector(spec.generating_sel) is None
                    el = page.query_selector(spec.send_sel) if spec.send_sel else None
                    return el is not None and el.is_enabled()

                _flow.wait_stream_done(page, done_predicate=_done, idle_ms=1500,
                                       timeout_s=120.0, cancel_token=cancel_token)
                html = page.content()
            answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
            cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                            exclude_hosts=spec.exclude_hosts)
            logger.info("[geo-rpa][yuanbao] kw=%s answer_len=%d cite_n=%d",
                        keyword, len(answer), len(cites))
            return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=answer,
                             citations=cites, status="ok" if answer else "empty",
                             raw={"html_len": len(html), "cite_n": len(cites)})
        except Exception as e:
            logger.exception("[geo-rpa][yuanbao] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error=str(e))
```

- [ ] **Step 5: 注册 + spec + 前端**

base.py：在 deepseek 分支后加 yuanbao 分支：
```python
    if platform == "yuanbao":
        try:
            from .rpa.yuanbao import YuanbaoProvider
        except ImportError as e:
            raise GeoProviderError(f"yuanbao provider 未就绪: {e}") from e
        return YuanbaoProvider()
```
spec：rpa.kimi 后加 `    "csm_core.monitor.geo.providers.rpa.yuanbao",`。
`monitor-types.ts`：`GEO_PLATFORMS` 加 `{ value: "yuanbao", label: "腾讯元宝", mode: "rpa" },`。

- [ ] **Step 6: 跑绿**

Run: `pytest tests/core/monitor/geo/ -v`
Expected: 全 passed。
Run（cwd=frontend）: `npm run test -- monitor-types && npx vue-tsc --noEmit` → PASS / 无新错。

- [ ] **Step 7: Commit**

```bash
git add csm_core/monitor/geo/providers/rpa/sites.py csm_core/monitor/geo/providers/rpa/yuanbao.py csm_core/monitor/geo/providers/base.py sidecar/csm-sidecar.spec frontend/src/utils/monitor-types.ts tests/core/monitor/geo/test_rpa_providers.py tests/core/monitor/geo/test_registration.py
git commit -m "feat(geo-rpa): 腾讯元宝 RPA provider + 注册 + GEO_PLATFORMS"
```

---

## Task 11: CHANGELOG + 人工验收清单 + 原生测试窗

**Files:**
- Modify: `CHANGELOG.md`（[Unreleased]）
- Create: `docs/superpowers/plans/2026-06-02-geo-phase3-rpa-acceptance.md`

- [ ] **Step 1: CHANGELOG [Unreleased] 加条目**

在 `CHANGELOG.md` 的 `## [Unreleased]` 段（无则在最新版本上方建）加：
```markdown
### Added
- GEO 阶段 3：AI 卡位新增「真浏览器 RPA」采集通道，覆盖 DeepSeek / Kimi / 腾讯元宝
  （这三家 API 拿不到联网信源）。DOM 交互：开真站→开联网→等流式→抓回答+来源链接，
  产出与 API provider 同形的 GeoAnswer，下游抽取/指标/告警/信源榜/引流闭环全复用。
  设置页新增「AI 卡位 · RPA 登录」分组（持久档登录，扫码/账号）。Kimi 由阶段 2 的
  API（无信源）改走 RPA 重新上线。geo_query 任务串行化 + 透传 cancel_token（长耗时
  RPA 可被「停止」及时中断）。

### Notes
- RPA 选择器随站点改版会失效，集中在 csm_core/monitor/geo/providers/rpa/sites.py，
  失效时改那里 + 重新校准（见 acceptance 清单）。夸克AI 不在本期。
```

- [ ] **Step 2: 写人工验收清单**

`docs/superpowers/plans/2026-06-02-geo-phase3-rpa-acceptance.md`：
```markdown
# GEO 阶段 3 RPA —— 人工验收清单（真站，不进 CI）

前置：worktree 重打 sidecar（PYTHONPATH 覆盖 editable）→ 拷 target/debug → tauri dev：
1. `set PYTHONPATH=<wt>;<wt>\sidecar & python scripts/build_sidecar.py --clean`
   （或对应 PowerShell 写法；产出 binaries/csm-sidecar-<triple>.exe）
2. 拷成 `frontend/src-tauri/target/debug/csm-sidecar.exe`；binaries 备 updater.exe + junction ms-playwright。
3. `cd frontend & npx tauri dev --no-watch`，等 stdout `sidecar handshake received: port=...`。

每个平台（DeepSeek → Kimi → 腾讯元宝）逐项：
- [ ] 设置页「AI 卡位 · RPA 登录」点「登录」→ 弹有头窗 → 完成登录（账号/短信/扫码）→ 窗口自动关 → 徽章变「已登录」。
- [ ] 关 dev、重启 → 徽章仍「已登录」（持久档生效）。
- [ ] **选择器校准**：登录态下手动在站内问一句、F12 复制回答容器 outerHTML；或临时在 provider 里 dump `page.content()` 到文件。比对 sites.py 的 answer_sel/citation_sel/composer_sel/web_toggle_sel/generating_sel/logged_in_sel/logged_out_sel，不符就改 sites.py。重点确认：
  - composer_sel 能定位输入框；web_toggle_sel 能切「联网」且 on_attr/on_value 对（不对则调 ensure_web_toggle 参数）；
  - generating_sel 在生成时在场、结束消失（wait_stream_done 据此判完成）；
  - citation_sel 容器内的来源 `<a href>` 被 extract_citations 抓到（exclude_hosts 排掉自家域名/站内导航）。
- [ ] 建 geo 任务（品牌+关键词）勾选该 RPA 平台 → run-now → 观察有头窗按预期打字/联网/等待 → 完成后：平台对比有该平台明细、信源榜有来源、答案文本入库。
- [ ] 未登录场景：删 `browser_profiles/geo_<platform>/` 或换平台未登录 → run → 该 cell 显示「采集失败/未登录」（blocked），不误报「未提及」，不崩。
- [ ] 「停止」：run 中点停止 → 当前 RPA 等待应 ~秒级中断（cancel_token 生效），不等满 120s。

回归：`pytest tests/core/monitor/geo/ -v` 全绿；`pytest sidecar/tests/test_monitor_routes.py -k geo_rpa` 全绿。
全套（发版前）：`npx npm@10 ci` 验证 lockfile（前端）。

**校准定稿后保存回归 fixture（落实 spec §7 的 per-site fixture）：**
- 把校准时抓的「回答容器」HTML 存到 `tests/core/monitor/geo/fixtures/<platform>_answer.html`（真站真 HTML）。
- 加回归测试 `tests/core/monitor/geo/test_rpa_fixtures.py`，每站一条：
  `assert _flow.extract_citations(open(FIX/'<platform>_answer.html').read(), container_sel=SITES['<platform>'].citation_sel)` 抽到该 fixture 里你眼见的预期来源 URL（锁住选择器，站点改版回归时 CI 立刻红）。
- 这步把「选择器对不对」从纯人工变成 CI 可回归，是 spec §7 的最终落地（只能在真 HTML 到手后做）。
```

- [ ] **Step 3: 全量回归（CI 安全部分）**

```bash
pytest tests/core/monitor/geo/ -v
pytest sidecar/tests/test_monitor_routes.py -v -k geo_rpa
```
Expected: 全 passed。
（cwd=frontend）`npm run test -- monitor-types` → PASS；`npx vue-tsc --noEmit` → 无新错。

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-02-geo-phase3-rpa-acceptance.md
git commit -m "docs(geo-rpa): CHANGELOG 阶段3条目 + 人工验收清单"
```

- [ ] **Step 5: 人工真站验收 + 选择器校准**

按 acceptance 清单在原生测试窗逐平台跑通（DeepSeek 先），校准 sites.py 选择器。**这是 PR 前的硬门槛**——CI 只证逻辑骨架，真站抓取必须人工验证过再推 PR。校准产生的 sites.py 改动单独提交：
```bash
git add csm_core/monitor/geo/providers/rpa/sites.py
git commit -m "fix(geo-rpa): 真站校准 DeepSeek/Kimi/元宝 选择器"
```

---

## 落地后（不属本计划，executing 时按既有约定）

- 全绿 + 人工验收通过 → push 分支 + `gh pr create`（停在 pending 等网页 merge；**不**本地 merge main）。
- PR footer：`🤖 Generated with [Claude Code](https://claude.com/claude-code)`；commit trailer：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- worktree 清理由用户手动（沙箱禁删 D:/CSM 下文件）。
