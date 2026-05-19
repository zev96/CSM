# Baidu Login Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the baidu_keyword monitor against `安全验证` 风控 by (1) reverting `_navigate_to_serp` to a single `page.goto(serp_url)` call, (2) adding an embedded patchright login webview so the persistent profile carries a real `BDUSS` cookie, and (3) gating each fetch on login state.

**Architecture:** 4 layers — simplify SERP nav (delete 3-stage home→fill→Enter), new `baidu_login.py` driver (open_login_window / get_login_status / detect_login_required), 2 sidecar routes for the settings UI, and a fetch-time BDUSS check that raises `RiskControlException(layer="auth")` so the existing runner pauses the task and the UI shows the breakpoint banner.

**Tech Stack:** Python 3.14 + patchright (stealth playwright fork) + FastAPI sidecar + Vue 3 (Tauri 2 desktop app). Pytest for backend. No JS test framework — frontend verified via `vue-tsc` + manual smoke.

**Reference spec:** [docs/superpowers/specs/2026-05-19-baidu-login-profile-design.md](../specs/2026-05-19-baidu-login-profile-design.md)

---

## File Structure

**New files**:
- `csm_core/monitor/drivers/baidu_login.py` — `open_login_window`, `get_login_status`, `detect_login_required`
- `sidecar/tests/test_baidu_login.py` — unit tests for the 3 baidu_login functions

**Modified files**:
- `csm_core/monitor/drivers/risk_detector.py` — extend `RiskLayer` Literal to include `"auth"`
- `csm_core/monitor/platforms/baidu_keyword.py` — simplify `_navigate_to_serp`, drop `is_first_keyword` arg, drop dead helpers, add BDUSS check + SERP post-check
- `sidecar/csm_sidecar/routes/monitor.py` — add `POST /api/monitor/baidu/login` + `GET /api/monitor/baidu/login-status`
- `sidecar/tests/routes/test_monitor.py` — add 3 tests for the 2 new routes
- `sidecar/tests/test_baidu_keyword.py` — replace 3 navigate tests, add 4 fetch-level auth tests
- `frontend/src/views/SettingsView.vue` — add Baidu account `SettingsRow` (state display + login button)
- `frontend/src/components/monitor/history/BaiduRankingPage.vue` — add `layer="auth"` branch to existing risk_control banner

---

## Task 1: Replace `_navigate_to_serp` tests with simplified expectations

**Files:**
- Test: `sidecar/tests/test_baidu_keyword.py:959-1140` (lines may shift slightly with edits)

Existing tests (`test_navigate_to_serp_first_keyword_goes_home`, `test_navigate_to_serp_subsequent_keyword_skips_home`, `test_navigate_to_serp_fills_with_force_and_submits_via_keyboard`) assert the 3-stage home→fill→Enter flow. After Task 2 the function will not call `fill` / `keyboard.press` at all. Replace these 3 tests with a smaller, sharper set that documents the new contract.

- [ ] **Step 1: Replace the three existing `_navigate_to_serp` tests**

Find the section starting at line 959 (`# ── _navigate_to_serp / _random_dwell_ms ───────────────────────────────`) and ending with the third test's closing line (the last `assert keyboard_call[1] == "Enter"` block around line 1139). Replace the entire section (delete the 3 tests + the comment header line) with:

```python
# ── _navigate_to_serp (simplified: direct goto(serp_url)) ──────────────


def test_navigate_to_serp_direct_goto():
    """_navigate_to_serp performs exactly one page.goto on the SERP url.

    The 3-stage home→fill→Enter flow was retired — its stable timing
    pattern was itself a bot signal. With persistent BDUSS the direct
    goto looks like a real user opening SERP from a bookmark / external
    link.
    """
    from csm_core.monitor.platforms import baidu_keyword

    calls: list[tuple] = []

    class FakePage:
        def goto(self, url, **kwargs):
            calls.append(("goto", url, kwargs))
            return "fake-response"

    response = baidu_keyword._navigate_to_serp(FakePage(), keyword="吸尘器")

    assert response == "fake-response"
    assert len(calls) == 1
    op, url, kwargs = calls[0]
    assert op == "goto"
    assert url.startswith("https://www.baidu.com/s?wd=")
    # quote() encodes 吸尘器 as %E5%90%B8%E5%B0%98%E5%99%A8
    assert "%E5%90%B8%E5%B0%98%E5%99%A8" in url
    assert kwargs.get("wait_until") == "domcontentloaded"
    assert kwargs.get("timeout") == 30000


def test_navigate_to_serp_does_not_touch_input_or_keyboard():
    """Guard against future regression: the function must NOT call
    fill / click / keyboard / mouse / wait_for_timeout — those were
    the bot-signal-leaking ops.
    """
    from csm_core.monitor.platforms import baidu_keyword

    forbidden_calls: list[str] = []

    class FakePage:
        def goto(self, url, **kwargs):
            return "fake-response"
        def fill(self, *a, **kw):
            forbidden_calls.append("fill")
        def click(self, *a, **kw):
            forbidden_calls.append("click")
        def wait_for_timeout(self, *a, **kw):
            forbidden_calls.append("wait_for_timeout")
        def expect_navigation(self, **kw):
            forbidden_calls.append("expect_navigation")
            raise AssertionError("should not be called")

    baidu_keyword._navigate_to_serp(FakePage(), keyword="test")

    assert forbidden_calls == [], (
        f"_navigate_to_serp should only call page.goto, got: {forbidden_calls}"
    )
```

- [ ] **Step 2: Run the new tests, verify they FAIL**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_navigate_to_serp_direct_goto tests/test_baidu_keyword.py::test_navigate_to_serp_does_not_touch_input_or_keyboard -v`

Expected: both FAIL. Current `_navigate_to_serp` signature requires `is_first_keyword` keyword arg (TypeError), and even bypassing that, it still calls `fill` / `wait_for_timeout` / `keyboard.press`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add sidecar/tests/test_baidu_keyword.py
git commit -m "test(monitor): rewrite _navigate_to_serp tests for direct goto contract"
```

---

## Task 2: Simplify `_navigate_to_serp` to a single `page.goto`

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py:398-473` (the entire `_navigate_to_serp` function body)

- [ ] **Step 1: Replace the function body**

Find `def _navigate_to_serp(page: Any, keyword: str, *, is_first_keyword: bool) -> Any:` at line 398. Replace the entire function (signature + docstring + all 75 lines of body) with:

```python
def _navigate_to_serp(page: Any, keyword: str) -> Any:
    """直接 goto SERP url。返回 navigation response 给 detect_risk 用。

    回归原架构 —— 三段式 home/fill/Enter 的时间 pattern 反而是 bot 信号。
    带登录态（BDUSS）的直接 goto 看起来像真实用户从书签或外链进 SERP，
    是 baidu organic 流量的主要形态。
    """
    serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
    return page.goto(serp_url, wait_until="domcontentloaded", timeout=30000)
```

- [ ] **Step 2: Run the new tests, verify they PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_navigate_to_serp_direct_goto tests/test_baidu_keyword.py::test_navigate_to_serp_does_not_touch_input_or_keyboard -v`

Expected: both PASS.

- [ ] **Step 3: Commit the implementation**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "refactor(monitor): simplify _navigate_to_serp to direct page.goto"
```

---

## Task 3: Clean up dead code that supported the 3-stage flow

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py` (helpers `_simulate_user_browsing`, `_random_dwell_ms`; caller `_fetch_once`)

After Task 2 these helpers have no callers. Remove them, plus the `is_first_keyword=(rel_idx == 0)` arg the caller used to pass.

- [ ] **Step 1: Find and delete `_simulate_user_browsing`**

Search the file for `def _simulate_user_browsing` (around line ~378). Delete the entire function definition. Also delete any leading section-comment line directly above it that no longer applies (e.g. lines that mention "real-user browsing simulation").

- [ ] **Step 2: Find and delete `_random_dwell_ms`**

Search for `def _random_dwell_ms`. Delete the entire function definition.

- [ ] **Step 3: Drop the `is_first_keyword` argument from the `_fetch_once` caller**

Find the line in `_fetch_once` that calls `_navigate_to_serp(...)` — it currently looks like:

```python
response = _navigate_to_serp(page, keyword, is_first_keyword=(rel_idx == 0))
```

Replace with:

```python
response = _navigate_to_serp(page, keyword)
```

(There should be only one such call in `_fetch_once`. If there's more than one, update all.)

- [ ] **Step 4: Drop unused imports**

`_simulate_user_browsing` likely used `random` (for `randint`/`uniform`). If `random` is no longer imported by any remaining code, delete `import random` from the file's import block. Verify by grep: `cd D:\CSM\.claude\worktrees\hopeful-elion-cff72a && grep -n "random\." csm_core/monitor/platforms/baidu_keyword.py` — if zero matches, drop the import; if matches remain, keep it.

- [ ] **Step 5: Run the full baidu_keyword test file**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py -v`

Expected: ALL tests pass, including the 2 new ones from Task 1. If any other test breaks because it referenced the deleted helpers, that test was testing the dead code — delete it.

- [ ] **Step 6: Commit the cleanup**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "refactor(monitor): drop dead _simulate_user_browsing and _random_dwell_ms"
```

---

## Task 4: Extend `RiskLayer` to include `"auth"`

**Files:**
- Modify: `csm_core/monitor/drivers/risk_detector.py:21`

`RiskLayer = Literal["url", "dom", "text", "http"]` needs `"auth"` so login-state failures raise the same `RiskControlException` type the runner already handles for risk_control breakpoints.

- [ ] **Step 1: Add the literal**

Find line 21 in `csm_core/monitor/drivers/risk_detector.py`:

```python
RiskLayer = Literal["url", "dom", "text", "http"]
```

Replace with:

```python
RiskLayer = Literal["url", "dom", "text", "http", "auth"]
```

- [ ] **Step 2: Run risk_detector tests to confirm no regression**

Run: `cd sidecar && python -m pytest tests/test_risk_detector.py -v` (or wherever risk_detector tests live; check with `grep -rl "from csm_core.monitor.drivers.risk_detector\|risk_detector" sidecar/tests/`).

Expected: all PASS. This is a strictly additive change so existing tests do not move.

- [ ] **Step 3: Commit**

```bash
git add csm_core/monitor/drivers/risk_detector.py
git commit -m "feat(monitor): extend RiskLayer with 'auth' for login-state failures"
```

---

## Task 5: TDD `detect_login_required` in new `baidu_login.py`

**Files:**
- Create: `csm_core/monitor/drivers/baidu_login.py`
- Create: `sidecar/tests/test_baidu_login.py`

`detect_login_required(response, page)` is the simplest of the 3 new functions — pure-Python URL + content inspection. Build it first to anchor the module.

- [ ] **Step 1: Write the failing tests**

Create `sidecar/tests/test_baidu_login.py` with:

```python
"""Tests for csm_core.monitor.drivers.baidu_login.

Three public functions:
- detect_login_required(response, page) -> bool
- get_login_status(user_data_dir) -> dict
- open_login_window(user_data_dir, *, timeout_s) -> dict
"""
from __future__ import annotations

from typing import Any


# ── detect_login_required ──────────────────────────────────────────────


class _FakeResp:
    def __init__(self, url: str):
        self.url = url


class _FakePage:
    def __init__(self, content_html: str = ""):
        self._content = content_html
    def content(self):
        return self._content


def test_detect_login_required_wappass_redirect():
    """wappass.baidu.com in the response URL is a login wall."""
    from csm_core.monitor.drivers import baidu_login

    resp = _FakeResp("https://wappass.baidu.com/static/captcha/tuxing.html?...")
    assert baidu_login.detect_login_required(resp, _FakePage()) is True


def test_detect_login_required_passport_redirect():
    """passport.baidu.com is the login page domain."""
    from csm_core.monitor.drivers import baidu_login

    resp = _FakeResp("https://passport.baidu.com/v2/?login&u=...")
    assert baidu_login.detect_login_required(resp, _FakePage()) is True


def test_detect_login_required_login_text_in_serp():
    """SERP returned 200 but body asks user to log in (server-side
    session invalidated even though cookie is still present)."""
    from csm_core.monitor.drivers import baidu_login

    resp = _FakeResp("https://www.baidu.com/s?wd=test")
    page = _FakePage(content_html="<html><body>请登录后查看搜索结果</body></html>")
    assert baidu_login.detect_login_required(resp, page) is True


def test_detect_login_required_normal_serp():
    """A real SERP is not a login wall."""
    from csm_core.monitor.drivers import baidu_login

    resp = _FakeResp("https://www.baidu.com/s?wd=test")
    page = _FakePage(content_html="<html><body><div class='c-container'>...</div></body></html>")
    assert baidu_login.detect_login_required(resp, page) is False


def test_detect_login_required_response_none():
    """response can be None (page.goto sometimes returns None on
    main-frame nav). detect_login_required must handle without crashing."""
    from csm_core.monitor.drivers import baidu_login

    page = _FakePage(content_html="<html>...</html>")
    assert baidu_login.detect_login_required(None, page) is False
```

- [ ] **Step 2: Run tests, verify they FAIL**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'csm_core.monitor.drivers.baidu_login'`.

- [ ] **Step 3: Create the module with `detect_login_required`**

Create `csm_core/monitor/drivers/baidu_login.py`:

```python
"""百度账号登录态管理：登录 webview / 状态读取 / SERP 后置兜底。

跟 baidu_browser.py 配套：baidu_browser_session 提供 persistent context
contextmanager；本模块提供登录态的写入（open_login_window）+ 读取
（get_login_status）+ 运行时兜底（detect_login_required）。

profile lock：open_login_window 跟 baidu_keyword task 抢同一个
user_data_dir。caller 在 sidecar route 里先 has_active_baidu_task 409 拦截。
"""
from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


# ── SERP-time check ────────────────────────────────────────────────────


# 跳到登录墙的 URL 域名子串。跟 risk_detector._URL_PATTERNS 有交集但语义
# 不同：risk_detector 是 "百度风控触发" (captcha)，这里是 "百度要求登录"。
# 业务后果一样（task 暂停），但用户在 UI 上看到的提示文案不同。
_LOGIN_REDIRECT_HOSTS = (
    "wappass.baidu.com",
    "passport.baidu.com",
)

# SERP 返回 200 但页面内有"请登录"类文案 —— server-side session 失效，
# cookie 看起来还在但已经被服务端撤销。覆盖几种常见话术。
_LOGIN_PROMPT_PHRASES = (
    "请登录",
    "登录后查看",
    "登录后体验",
)


def detect_login_required(response: Any, page: Any) -> bool:
    """判断这次 SERP 响应是否实际把我们打回登录墙。

    SERP 后置兜底用 —— 主流程在 fetch 入口已经读过 BDUSS cookie，但
    server-side session 可能先于 cookie expires_at 失效（cookie 看着
    还在但服务端不认）。这时 SERP 会跳 passport / wappass，或 200 OK
    body 含"请登录"文案。

    Args:
        response: page.goto 的返回值，可能为 None（main-frame nav 时偶发）。
        page: patchright Page handle。content() 失败时 fail-soft。

    Returns:
        True = 命中登录墙；False = 正常 SERP。
    """
    # Layer 1: response.url 子串匹配 —— 最便宜的一层，先跑。
    try:
        url = getattr(response, "url", "") or ""
        for host in _LOGIN_REDIRECT_HOSTS:
            if host in url:
                return True
    except Exception:
        pass

    # Layer 2: page.content() 文本检查 —— cookie 还在但 server session
    # 失效时 SERP 仍 200 但 body 文案变了。
    try:
        html = page.content() if hasattr(page, "content") else ""
        for phrase in _LOGIN_PROMPT_PHRASES:
            if phrase in html:
                return True
    except Exception as e:
        # 不能让一个 content() 异常阻塞 SERP 解析。debug-log，返回 False。
        logger.debug("detect_login_required content() raised: %s", e)
        return False

    return False
```

- [ ] **Step 4: Run tests, verify all 5 PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py -v`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/drivers/baidu_login.py sidecar/tests/test_baidu_login.py
git commit -m "feat(monitor): add baidu_login.detect_login_required for SERP fallback check"
```

---

## Task 6: TDD `get_login_status` (cookie + meta file)

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_login.py`
- Modify: `sidecar/tests/test_baidu_login.py`

`get_login_status(user_data_dir)` opens a short-lived persistent context, reads cookies for baidu.com, then reads `.csm_login_meta.json` for the cached username.

- [ ] **Step 1: Add the failing tests**

Append to `sidecar/tests/test_baidu_login.py`:

```python
# ── get_login_status ────────────────────────────────────────────────────


import json
import time
from pathlib import Path

import pytest


class _FakeCtx:
    """Stand-in for patchright BrowserContext: only .cookies + .close."""
    def __init__(self, cookies_to_return: list[dict[str, Any]]):
        self._cookies = list(cookies_to_return)
        self.close_called = False
    def cookies(self, url: str | None = None):
        return list(self._cookies)
    def close(self):
        self.close_called = True


class _FakeChromium:
    def __init__(self, cookies_to_return: list[dict[str, Any]]):
        self.context = _FakeCtx(cookies_to_return)
    def launch_persistent_context(self, user_data_dir, **kwargs):
        return self.context


class _FakePW:
    def __init__(self, cookies_to_return: list[dict[str, Any]]):
        self.chromium = _FakeChromium(cookies_to_return)
        self.stop_called = False
    def stop(self):
        self.stop_called = True


class _FakeSyncPW:
    def __init__(self, pw: _FakePW):
        self._pw = pw
    def start(self):
        return self._pw


@pytest.fixture
def fake_pw_factory(monkeypatch):
    """Wires baidu_login's playwright entry-point to a fake. Returns a
    factory: call with the cookies list you want to surface."""
    from csm_core.monitor.drivers import baidu_login

    def make(cookies: list[dict[str, Any]]) -> _FakePW:
        pw = _FakePW(cookies)
        monkeypatch.setattr(baidu_login, "_sync_playwright", lambda: _FakeSyncPW(pw))
        monkeypatch.setattr(baidu_login, "ensure_browsers_path", lambda: None)
        return pw
    return make


def test_get_login_status_not_logged_in(fake_pw_factory, tmp_path):
    """No BDUSS cookie → logged_in=False, username=None."""
    from csm_core.monitor.drivers import baidu_login

    fake_pw_factory([])  # no cookies

    status = baidu_login.get_login_status(user_data_dir=tmp_path / "profile")

    assert status == {"logged_in": False, "username": None, "expires_at": None}


def test_get_login_status_logged_in_with_meta(fake_pw_factory, tmp_path):
    """BDUSS cookie present + meta file present → logged_in=True + username."""
    from csm_core.monitor.drivers import baidu_login

    future = time.time() + 30 * 86400  # 30 days out
    fake_pw_factory([
        {"name": "BDUSS", "value": "abc", "expires": future, "domain": ".baidu.com"},
    ])

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / ".csm_login_meta.json").write_text(
        json.dumps({"username": "testuser", "logged_in_at": "2026-05-19T15:00:00Z"}),
        encoding="utf-8",
    )

    status = baidu_login.get_login_status(user_data_dir=profile)

    assert status["logged_in"] is True
    assert status["username"] == "testuser"
    # expires_at is an ISO-8601 string derived from the epoch float
    assert status["expires_at"] is not None
    assert "T" in status["expires_at"]  # crude ISO check


def test_get_login_status_expired_cookie(fake_pw_factory, tmp_path):
    """BDUSS expires < now → logged_in=False even though the cookie exists."""
    from csm_core.monitor.drivers import baidu_login

    past = time.time() - 86400  # 1 day ago
    fake_pw_factory([
        {"name": "BDUSS", "value": "stale", "expires": past, "domain": ".baidu.com"},
    ])

    status = baidu_login.get_login_status(user_data_dir=tmp_path / "profile")

    assert status["logged_in"] is False
    assert status["username"] is None


def test_get_login_status_logged_in_without_meta(fake_pw_factory, tmp_path):
    """BDUSS present but meta file missing → logged_in=True, username=None.
    Frontend falls back to '已登录' without name."""
    from csm_core.monitor.drivers import baidu_login

    future = time.time() + 86400
    fake_pw_factory([
        {"name": "BDUSS", "value": "abc", "expires": future, "domain": ".baidu.com"},
    ])

    status = baidu_login.get_login_status(user_data_dir=tmp_path / "profile_no_meta")

    assert status["logged_in"] is True
    assert status["username"] is None


def test_get_login_status_session_cookie_no_expires(fake_pw_factory, tmp_path):
    """BDUSS with expires=-1 (session cookie) is treated as valid —
    baidu uses -1 for cookies that survive the browser session but
    have no fixed expiry."""
    from csm_core.monitor.drivers import baidu_login

    fake_pw_factory([
        {"name": "BDUSS", "value": "abc", "expires": -1, "domain": ".baidu.com"},
    ])

    status = baidu_login.get_login_status(user_data_dir=tmp_path / "profile")

    assert status["logged_in"] is True
    assert status["expires_at"] is None  # no fixed expiry to surface
```

- [ ] **Step 2: Run tests, verify they FAIL**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py::test_get_login_status_not_logged_in tests/test_baidu_login.py::test_get_login_status_logged_in_with_meta tests/test_baidu_login.py::test_get_login_status_expired_cookie tests/test_baidu_login.py::test_get_login_status_logged_in_without_meta tests/test_baidu_login.py::test_get_login_status_session_cookie_no_expires -v`

Expected: all 5 FAIL with `AttributeError: module 'csm_core.monitor.drivers.baidu_login' has no attribute 'get_login_status'` (or similar).

- [ ] **Step 3: Implement `get_login_status` + supporting helpers**

Append to `csm_core/monitor/drivers/baidu_login.py`:

```python
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .patchright_pool import ensure_browsers_path

# ── module-level indirection for monkeypatching in tests ──────────────


def _sync_playwright() -> Any:
    """Indirection so unit tests can monkeypatch a fake. Mirrors the
    same pattern in baidu_browser._sync_playwright."""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


def _default_user_data_dir() -> Path:
    """Same path as baidu_browser._default_user_data_dir — single profile
    shared between login window and fetch tasks."""
    from csm_sidecar.services import config_service
    return config_service.get_path().parent / "baidu_browser_profile"


_META_FILENAME = ".csm_login_meta.json"


# ── get_login_status ───────────────────────────────────────────────────


def get_login_status(user_data_dir: Path | None = None) -> dict[str, Any]:
    """读 persistent profile 看登录态。不弹窗。

    实现：launch_persistent_context(headless=True) 短时启动，读
    cookies("https://www.baidu.com/")，立刻关。开销 ~2s，settings 页
    打开时调一次能接受。

    BDUSS 不在 → logged_in=False。
    BDUSS 在但 expires < now → logged_in=False (cookie 已过期)。
    BDUSS 在且未过期 → logged_in=True，username 从 user_data_dir /
        ".csm_login_meta.json" 读取（open_login_window 成功时写入）。

    Returns:
        {"logged_in": bool, "username": str | None, "expires_at": str | None}
    """
    ensure_browsers_path()
    target_dir = user_data_dir or _default_user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=True,
        )
        try:
            cookies = context.cookies("https://www.baidu.com/")
        except Exception as e:
            logger.debug("get_login_status cookies() raised: %s", e)
            cookies = []
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("get_login_status context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("get_login_status pw.stop raised: %s", e)

    return _status_from_cookies(cookies, target_dir)


def _status_from_cookies(
    cookies: list[dict[str, Any]], user_data_dir: Path,
) -> dict[str, Any]:
    """Cookie 列表 → status dict。pure logic，单独抽出便于测。"""
    bduss = next((c for c in cookies if c.get("name") == "BDUSS"), None)
    if bduss is None:
        return {"logged_in": False, "username": None, "expires_at": None}

    # expires = -1 表示 session cookie，对登录态来说视为有效（baidu 实际
    # 用 -1 标记长效凭据），expires_at 返回 None。
    expires = bduss.get("expires")
    if expires is not None and expires != -1 and expires < time.time():
        return {"logged_in": False, "username": None, "expires_at": None}

    expires_at: str | None = None
    if expires is not None and expires != -1:
        expires_at = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()

    username = _read_username(user_data_dir)
    return {"logged_in": True, "username": username, "expires_at": expires_at}


def _read_username(user_data_dir: Path) -> str | None:
    """Read .csm_login_meta.json. Missing file or parse failure → None."""
    meta_path = user_data_dir / _META_FILENAME
    try:
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        name = data.get("username")
        return name if isinstance(name, str) and name else None
    except Exception as e:
        logger.debug("read .csm_login_meta.json failed: %s", e)
        return None
```

- [ ] **Step 4: Run tests, verify all 5 PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py -v`

Expected: 5 detect tests + 5 get_login_status tests = 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/drivers/baidu_login.py sidecar/tests/test_baidu_login.py
git commit -m "feat(monitor): add baidu_login.get_login_status reading BDUSS + meta"
```

---

## Task 7: TDD `open_login_window` — success path

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_login.py`
- Modify: `sidecar/tests/test_baidu_login.py`

`open_login_window` opens a visible Chromium, polls cookies for BDUSS appearance, writes meta file, returns. This task covers the **success** path; Task 8 covers cancelled + timeout.

- [ ] **Step 1: Add the failing test**

Append to `sidecar/tests/test_baidu_login.py`:

```python
# ── open_login_window ──────────────────────────────────────────────────


class _PollingCtx:
    """Cookies start empty, then return BDUSS after N polls. Mimics user
    completing login mid-window. Tracks goto/close/headers for assertion."""

    def __init__(self, bduss_appears_after_polls: int = 1):
        self._counter = 0
        self._threshold = bduss_appears_after_polls
        self.close_called = False
        self.goto_urls: list[str] = []
        # Simulate the BrowserContext lifecycle handler API
        self._close_listeners: list[Any] = []
        self.pages: list[Any] = []
        # Pre-create one page (persistent context returns one by default)
        self.pages.append(self._make_page())

    def _make_page(self):
        outer = self
        class P:
            def goto(self, url, **kwargs):
                outer.goto_urls.append(url)
            def bring_to_front(self):
                pass
        return P()

    def new_page(self):
        page = self._make_page()
        self.pages.append(page)
        return page

    def cookies(self, url: str | None = None):
        self._counter += 1
        if self._counter > self._threshold:
            return [{"name": "BDUSS", "value": "xyz",
                     "expires": time.time() + 86400 * 30,
                     "domain": ".baidu.com"}]
        return []

    def close(self):
        self.close_called = True

    def on(self, event_name: str, handler: Any):
        if event_name == "close":
            self._close_listeners.append(handler)


class _PollingChromium:
    def __init__(self, ctx: _PollingCtx):
        self.context = ctx
        self.last_kwargs: dict[str, Any] = {}
    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.last_kwargs = kwargs
        return self.context


class _PollingPW:
    def __init__(self, ctx: _PollingCtx):
        self.chromium = _PollingChromium(ctx)
        self.stop_called = False
    def stop(self):
        self.stop_called = True


def test_open_login_window_success(monkeypatch, tmp_path):
    """BDUSS appears on second poll → status='success', context closed,
    meta file written, headless=False, baidu.com goto'd."""
    from csm_core.monitor.drivers import baidu_login

    ctx = _PollingCtx(bduss_appears_after_polls=1)
    pw = _PollingPW(ctx)
    monkeypatch.setattr(baidu_login, "_sync_playwright", lambda: _FakeSyncPW(pw))
    monkeypatch.setattr(baidu_login, "ensure_browsers_path", lambda: None)
    # Short poll interval so the test runs fast
    monkeypatch.setattr(baidu_login, "_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(baidu_login, "_POST_LOGIN_SETTLE_S", 0.01)
    # Stub out the optional username-fetch — keep it pure
    monkeypatch.setattr(baidu_login, "_fetch_username_from_passport",
                        lambda ctx: "puseruser")

    profile = tmp_path / "profile"
    result = baidu_login.open_login_window(user_data_dir=profile, timeout_s=5)

    assert result["status"] == "success"
    assert result["username"] == "puseruser"
    assert ctx.close_called is True
    # The window was opened on baidu.com so user can click 登录
    assert any("baidu.com" in u for u in ctx.goto_urls)
    # Must be headed (so user can interact)
    assert pw.chromium.last_kwargs.get("headless") is False
    # Meta file persisted for get_login_status to read later
    meta_path = profile / ".csm_login_meta.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["username"] == "puseruser"
    assert "logged_in_at" in data
```

- [ ] **Step 2: Run test, verify it FAILS**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py::test_open_login_window_success -v`

Expected: FAIL — `open_login_window`, `_POLL_INTERVAL_S`, `_POST_LOGIN_SETTLE_S`, `_fetch_username_from_passport` don't exist yet.

- [ ] **Step 3: Implement `open_login_window` (success path)**

Append to `csm_core/monitor/drivers/baidu_login.py`:

```python
# ── open_login_window ──────────────────────────────────────────────────


# Tunable in tests via monkeypatch
_POLL_INTERVAL_S = 3.0
# After BDUSS shows up, sleep this long so the rest of the login cookies
# (PTOKEN/STOKEN/PASS_TICKET) finish landing on disk before we close.
_POST_LOGIN_SETTLE_S = 2.0


def open_login_window(
    user_data_dir: Path | None = None,
    *,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """开一个可见 patchright headed 窗口让用户登录百度。

    流程：
    1. launch_persistent_context(headless=False) 在 baidu profile 上开窗
    2. page.goto("https://www.baidu.com/") + bring_to_front
    3. 每 _POLL_INTERVAL_S 秒 poll context.cookies，检测 BDUSS 是否出现
    4. 同时监听 BrowserContext "close" 事件（用户手动关窗）
    5. BDUSS 命中 → 等 _POST_LOGIN_SETTLE_S 让其他登录 cookie 落盘 → close
    6. 用户关窗 → 立即返回 cancelled
    7. timeout_s 达到 → 关窗 + 返回 timeout

    success 时写 user_data_dir / .csm_login_meta.json，供 get_login_status
    后续读取。

    Returns:
        {"status": "success" | "cancelled" | "timeout", "username": str | None}
    """
    ensure_browsers_path()
    target_dir = user_data_dir or _default_user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,800",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # User-closed flag — toggled via the context "close" event listener
        # below. _open_login_poll respects it.
        state = {"closed_by_user": False}
        def _on_close(_evt=None):
            state["closed_by_user"] = True
        try:
            context.on("close", _on_close)
        except Exception as e:
            # FakeContext in tests may not implement on(). Log + continue.
            logger.debug("context.on('close') not available: %s", e)

        try:
            page.goto("https://www.baidu.com/")
            try:
                page.bring_to_front()
            except Exception:
                pass
        except Exception as e:
            logger.warning("open_login_window goto failed: %s", e)

        outcome = _open_login_poll(context, state, timeout_s)
        if outcome == "success":
            time.sleep(_POST_LOGIN_SETTLE_S)
            username = _fetch_username_from_passport(context)
            _write_login_meta(target_dir, username)
            return {"status": "success", "username": username}
        return {"status": outcome, "username": None}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("open_login_window context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("open_login_window pw.stop raised: %s", e)


def _open_login_poll(context: Any, state: dict[str, bool], timeout_s: int) -> str:
    """Poll until BDUSS appears, user closes window, or timeout. Returns
    one of: 'success', 'cancelled', 'timeout'."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if state.get("closed_by_user"):
            return "cancelled"
        try:
            cookies = context.cookies("https://www.baidu.com/")
        except Exception as e:
            logger.debug("poll cookies() raised: %s", e)
            cookies = []
        if any(c.get("name") == "BDUSS" for c in cookies):
            return "success"
        time.sleep(_POLL_INTERVAL_S)
    return "timeout"


def _fetch_username_from_passport(context: Any) -> str | None:
    """Best-effort: hit baidu passport's logininfo endpoint inside the
    same context (cookies attached) to retrieve the username. Failure
    is non-fatal — success without a username still counts as logged in.
    """
    # passport API is unstable/private; defer real impl. Returning None
    # is fine — the frontend falls back to "已登录" without name.
    return None


def _write_login_meta(user_data_dir: Path, username: str | None) -> None:
    """Write the meta file get_login_status reads."""
    meta = {
        "username": username,
        "logged_in_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    try:
        (user_data_dir / _META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8",
        )
    except Exception as e:
        logger.warning("write .csm_login_meta.json failed: %s", e)
```

- [ ] **Step 4: Run test, verify PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py::test_open_login_window_success -v`

Expected: PASS.

- [ ] **Step 5: Run the whole test file to make sure nothing else broke**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py -v`

Expected: 11 PASS (5 detect + 5 status + 1 open success).

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/drivers/baidu_login.py sidecar/tests/test_baidu_login.py
git commit -m "feat(monitor): add open_login_window success path with BDUSS polling"
```

---

## Task 8: `open_login_window` — cancelled and timeout paths

**Files:**
- Modify: `sidecar/tests/test_baidu_login.py` (add 2 tests)

The success path drove the basic impl. Now lock in the failure paths.

- [ ] **Step 1: Add the failing tests**

Append to `sidecar/tests/test_baidu_login.py`:

```python
def test_open_login_window_cancelled(monkeypatch, tmp_path):
    """User closes the webview before logging in → status='cancelled'.
    Meta file is NOT written."""
    from csm_core.monitor.drivers import baidu_login

    # Cookies never return BDUSS, but we simulate the user-close event
    # firing on the first poll tick.
    ctx = _PollingCtx(bduss_appears_after_polls=10_000)
    pw = _PollingPW(ctx)
    monkeypatch.setattr(baidu_login, "_sync_playwright", lambda: _FakeSyncPW(pw))
    monkeypatch.setattr(baidu_login, "ensure_browsers_path", lambda: None)
    monkeypatch.setattr(baidu_login, "_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(baidu_login, "_POST_LOGIN_SETTLE_S", 0.0)

    # Trigger the user-close event after the first poll. We register
    # a sentinel handler on the fake context that toggles the state.
    original_on = ctx.on
    captured_state: dict[str, Any] = {}
    def _on(event_name, handler):
        original_on(event_name, handler)
        if event_name == "close":
            captured_state["handler"] = handler
    ctx.on = _on  # type: ignore[assignment]

    # Patch the poll loop to fire the close event mid-flight.
    real_poll = baidu_login._open_login_poll
    def _intercept_poll(context, state, timeout_s):
        # Simulate user closing the window after one tick: just flip the
        # state flag the real poll loop checks.
        state["closed_by_user"] = True
        return real_poll(context, state, timeout_s)
    monkeypatch.setattr(baidu_login, "_open_login_poll", _intercept_poll)

    profile = tmp_path / "profile"
    result = baidu_login.open_login_window(user_data_dir=profile, timeout_s=5)

    assert result == {"status": "cancelled", "username": None}
    assert not (profile / ".csm_login_meta.json").exists()


def test_open_login_window_timeout(monkeypatch, tmp_path):
    """timeout_s elapses without BDUSS → status='timeout'."""
    from csm_core.monitor.drivers import baidu_login

    ctx = _PollingCtx(bduss_appears_after_polls=10_000)
    pw = _PollingPW(ctx)
    monkeypatch.setattr(baidu_login, "_sync_playwright", lambda: _FakeSyncPW(pw))
    monkeypatch.setattr(baidu_login, "ensure_browsers_path", lambda: None)
    monkeypatch.setattr(baidu_login, "_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(baidu_login, "_POST_LOGIN_SETTLE_S", 0.0)

    profile = tmp_path / "profile"
    # Sub-second timeout so the test finishes fast
    result = baidu_login.open_login_window(user_data_dir=profile, timeout_s=0.05)

    assert result == {"status": "timeout", "username": None}
    assert not (profile / ".csm_login_meta.json").exists()
```

- [ ] **Step 2: Run the new tests, verify they PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_login.py::test_open_login_window_cancelled tests/test_baidu_login.py::test_open_login_window_timeout -v`

Expected: both PASS. The current impl already handles these — the tests just lock them in.

Note on the timeout test: `timeout_s` is annotated `int` in the signature but Python is duck-typed and `time.time() + 0.05` is fine. If the type-strict pytest fails on this, change the signature to `timeout_s: float = 600` so int 600 still works for callers but float 0.05 works in tests.

- [ ] **Step 3: Commit**

```bash
git add sidecar/tests/test_baidu_login.py
git commit -m "test(monitor): cover open_login_window cancelled and timeout paths"
```

---

## Task 9: `POST /api/monitor/baidu/login` route + tests

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`
- Modify: `sidecar/tests/routes/test_monitor.py`

Follows the exact same pattern as the existing `POST /api/monitor/baidu/reset-profile` route at `monitor.py:357-376` — `has_active_baidu_task()` 409 gate, then call into csm_core.

- [ ] **Step 1: Write the failing route tests**

Append to `sidecar/tests/routes/test_monitor.py`:

```python
def test_baidu_login_409_when_baidu_task_running(client):
    """If a baidu task is active, login should refuse with 409 (would
    fight for the same profile lock)."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_login.open_login_window"
        ) as mock_open:
            resp = client.post("/api/monitor/baidu/login")
        assert resp.status_code == 409
        assert "百度任务" in resp.json().get("detail", "")
        mock_open.assert_not_called()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_baidu_login_success_proxies_result(client):
    """No active baidu task → open_login_window is called, its dict
    result is proxied back to the client."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: False})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_login.open_login_window",
            return_value={"status": "success", "username": "testuser"},
        ) as mock_open:
            resp = client.post("/api/monitor/baidu/login")
        assert resp.status_code == 200
        assert resp.json() == {"status": "success", "username": "testuser"}
        mock_open.assert_called_once()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001
```

- [ ] **Step 2: Run tests, verify they FAIL**

Run: `cd sidecar && python -m pytest tests/routes/test_monitor.py::test_baidu_login_409_when_baidu_task_running tests/routes/test_monitor.py::test_baidu_login_success_proxies_result -v`

Expected: both FAIL — route returns 404.

- [ ] **Step 3: Add the route**

In `sidecar/csm_sidecar/routes/monitor.py`, find the `# ── Baidu browser profile management ──────────────────────────────────────` section at line 356. **Right after** the existing `reset_baidu_profile` function (around line 376), append:

```python


@router.post("/api/monitor/baidu/login")
async def baidu_login_open() -> dict[str, Any]:
    """Open a visible patchright window so the user can log in to Baidu.
    Persistent cookies land in the same profile dir that fetch tasks use.

    Refuses (409) if a baidu task is running — they share the same
    user_data_dir lock.
    """
    from csm_core.monitor.drivers.baidu_login import open_login_window
    from ..services import monitor_lifecycle

    loop = monitor_lifecycle.get()
    if loop is not None and loop.has_active_baidu_task():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="有正在运行的百度任务，先停止再登录",
        )
    return open_login_window()
```

Verify that `Any` is already imported at the top of `monitor.py` — search for `from typing import` near the top. If `Any` isn't in the list, add it. Same for `HTTPException` and `status` (these should already be imported because `reset_baidu_profile` uses them).

- [ ] **Step 4: Run tests, verify PASS**

Run: `cd sidecar && python -m pytest tests/routes/test_monitor.py -v`

Expected: all PASS (existing reset tests + 2 new login tests).

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/routes/test_monitor.py
git commit -m "feat(sidecar): POST /api/monitor/baidu/login opens patchright login window"
```

---

## Task 10: `GET /api/monitor/baidu/login-status` route + test

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`
- Modify: `sidecar/tests/routes/test_monitor.py`

- [ ] **Step 1: Write the failing test**

Append to `sidecar/tests/routes/test_monitor.py`:

```python
def test_baidu_login_status_proxies_result(client):
    """GET login-status returns whatever get_login_status produced.
    No 409 gate — read-only operation, safe even with a baidu task running."""
    from unittest.mock import patch

    with patch(
        "csm_core.monitor.drivers.baidu_login.get_login_status",
        return_value={
            "logged_in": True,
            "username": "testuser",
            "expires_at": "2026-07-01T00:00:00+00:00",
        },
    ) as mock_status:
        resp = client.get("/api/monitor/baidu/login-status")

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": True,
        "username": "testuser",
        "expires_at": "2026-07-01T00:00:00+00:00",
    }
    mock_status.assert_called_once()
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `cd sidecar && python -m pytest tests/routes/test_monitor.py::test_baidu_login_status_proxies_result -v`

Expected: FAIL with 404.

- [ ] **Step 3: Add the route**

In `sidecar/csm_sidecar/routes/monitor.py`, append after the `baidu_login_open` function from Task 9:

```python


@router.get("/api/monitor/baidu/login-status")
async def baidu_login_status() -> dict[str, Any]:
    """Read-only login state probe used by the settings page.

    Briefly launches a headless persistent context (~2s) to read cookies.
    Failures degrade to {logged_in: False} rather than 5xx — settings UI
    shouldn't blow up if the profile is corrupt.
    """
    from csm_core.monitor.drivers.baidu_login import get_login_status

    try:
        return get_login_status()
    except Exception as e:
        # Soft fallback so the UI keeps functioning
        import logging
        logging.getLogger(__name__).warning("baidu login-status read failed: %s", e)
        return {"logged_in": False, "username": None, "expires_at": None}
```

- [ ] **Step 4: Run test, verify PASS**

Run: `cd sidecar && python -m pytest tests/routes/test_monitor.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/routes/test_monitor.py
git commit -m "feat(sidecar): GET /api/monitor/baidu/login-status returns BDUSS state"
```

---

## Task 11: SettingsView UI — Baidu account row

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

Add a new `SettingsRow` directly above the existing "重置百度浏览器 profile" row at line 1555.

- [ ] **Step 1: Add state and handlers to the `<script setup>` block**

Find the `confirmResetBaiduProfile` function at line 626. Immediately **after** its closing `}` (around line 637), insert:

```typescript
// ── Baidu account login state ────────────────────────────────────────
const baiduLoginStatus = ref<{
  logged_in: boolean;
  username: string | null;
  expires_at: string | null;
}>({ logged_in: false, username: null, expires_at: null });
const baiduLoginBusy = ref(false);

async function refreshBaiduLoginStatus() {
  try {
    const r = await sidecar.client.get("/api/monitor/baidu/login-status");
    baiduLoginStatus.value = {
      logged_in: !!r.data?.logged_in,
      username: r.data?.username ?? null,
      expires_at: r.data?.expires_at ?? null,
    };
  } catch (e) {
    // Settings page shouldn't blow up if sidecar is wedged; just show "未登录"
    baiduLoginStatus.value = { logged_in: false, username: null, expires_at: null };
  }
}

async function startBaiduLogin() {
  const msg = baiduLoginStatus.value.logged_in
    ? "重新登录百度账号？\n会打开一个浏览器窗口，登录新账号后旧登录态会被覆盖。"
    : "登录百度账号？\n会打开一个浏览器窗口，登录后 CSM 抓取任务自动用登录态访问。\n建议使用专用账号，避免日常使用的账号被风控。";
  if (!confirm(msg)) return;

  baiduLoginBusy.value = true;
  try {
    const r = await sidecar.client.post("/api/monitor/baidu/login");
    const status = r.data?.status;
    if (status === "success") {
      toast.success("百度账号登录成功");
    } else if (status === "cancelled") {
      toast.info("登录已取消");
    } else if (status === "timeout") {
      toast.error("登录超时（窗口已关闭）");
    } else {
      toast.error(`登录失败：未知状态 ${status}`);
    }
  } catch (e: any) {
    const detail = e.response?.data?.detail ?? e.message ?? "未知错误";
    toast.error(`登录失败：${detail}`);
  } finally {
    baiduLoginBusy.value = false;
    await refreshBaiduLoginStatus();
  }
}

// Refresh once when settings mount — keep close to other onMounted blocks.
// If there's an existing onMounted in this file, append a call there
// instead of registering a second one.
onMounted(() => {
  refreshBaiduLoginStatus();
});
```

Then verify the imports at the top of `<script setup>` include `ref`, `onMounted`. Search the top of the script block — if `onMounted` is not in the `import { ... } from "vue"` line, add it.

- [ ] **Step 2: Add the template row**

Find the existing `SettingsRow label="重置百度浏览器 profile"` block at line 1555-1564. **Immediately before** that row (i.e., directly after the closing `</SettingsRow>` of "默认排除域名"), insert:

```vue
<SettingsRow
  label="百度账号"
  hint="CSM 抓取任务用登录态访问百度，显著降低风控触发率。建议使用专用账号 —— 万一被风控，不会影响你日常使用的账号。"
>
  <div class="flex items-center gap-3">
    <span
      v-if="baiduLoginStatus.logged_in"
      class="text-[11.5px]"
      :style="{ color: 'var(--success, #16a34a)' }"
    >
      已登录{{ baiduLoginStatus.username ? ` @${baiduLoginStatus.username}` : "" }}
    </span>
    <span
      v-else
      class="text-[11.5px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      未登录
    </span>
    <Btn
      :variant="baiduLoginStatus.logged_in ? 'solid' : 'primary'"
      small
      :disabled="baiduLoginBusy"
      @click="startBaiduLogin"
    >
      <Icon name="user" :size="12" />
      <span>{{ baiduLoginStatus.logged_in ? "重新登录" : "登录百度" }}</span>
    </Btn>
  </div>
</SettingsRow>
```

Notes for the engineer:
- If `Btn` doesn't have a `"primary"` variant, replace it with `"solid"` (the existing "管理排除域名" button at line 1549 uses `variant="solid"`).
- If `Icon name="user"` isn't in the icon set, drop the `<Icon ...>` line entirely — the text label is enough.

- [ ] **Step 3: Build + smoke**

Run: `cd frontend && npm run build`

Expected: PASS (vue-tsc clean, vite bundles successfully).

Then start the dev stack: `cd frontend && npm run tauri:dev` (or use the project's `dev.ps1` if it exists). Open the settings page, scroll to the 百度 section. Confirm:
- New row "百度账号" appears
- Shows "未登录" (since no login happened yet)
- Clicking "登录百度" opens a confirm dialog
- Clicking OK on the confirm fires the POST and either opens a patchright window OR shows a 409 toast if a baidu task is running

(Don't actually complete the login here — that's Task 15's smoke step. Just verify the wiring.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(frontend): add 百度账号 row to settings with login button"
```

---

## Task 12: TDD `_fetch_once` BDUSS check (raise auth risk_control)

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

The pre-flight BDUSS check is the heart of Layer 3 — without it, a logged-out user's fetch would still send anonymous requests and hit the same 风控 problem.

- [ ] **Step 1: Add the failing tests**

Find a good insertion point in `sidecar/tests/test_baidu_keyword.py` — search for `def test_fetch_` to find the existing `fetch` test cluster. Append:

```python
# ── fetch BDUSS pre-flight check ──────────────────────────────────────


def test_fetch_raises_auth_risk_control_when_not_logged_in(monkeypatch):
    """If session.context.cookies returns no BDUSS, fetch must raise
    RiskControlException(layer='auth') with progress=resume_from before
    making a single SERP request."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    class FakeContext:
        def cookies(self, url=None):
            return []  # no BDUSS — logged out

    class FakePage:
        def goto(self, url, **kwargs):
            raise AssertionError("should not reach goto when not logged in")

    class FakeSession:
        def __init__(self):
            self.page = FakePage()
            self.context = FakeContext()

    from contextlib import contextmanager
    @contextmanager
    def fake_session(*, headless, user_data_dir=None):
        yield FakeSession()

    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", fake_session)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    task = MonitorTask(
        id=42, type="baidu_keyword",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keywords": ["吸尘器", "洗碗机"], "target_brand": "CEWEY"},
    )

    try:
        adapter.fetch(task, resume_from=1)
    except RiskControlException as e:
        assert e.signal.layer == "auth"
        assert "登录" in e.signal.detail or "BDUSS" in e.signal.detail
        assert e.progress == 1
    else:
        raise AssertionError("expected RiskControlException")


def test_assert_baidu_logged_in_passes_when_bduss_present():
    """The pure helper used by _fetch_once must NOT raise when BDUSS
    is in the cookie list."""
    from csm_core.monitor.platforms import baidu_keyword

    adapter = baidu_keyword.BaiduKeywordAdapter()
    cookies = [
        {"name": "BAIDUID", "value": "irrelevant"},
        {"name": "BDUSS", "value": "abc"},
    ]
    # Should not raise
    adapter._assert_baidu_logged_in(cookies, resume_from=0)


def test_assert_baidu_logged_in_raises_auth_when_bduss_missing():
    """Same helper raises RiskControlException(layer='auth') when BDUSS
    is missing, with progress = resume_from passed through."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    adapter = baidu_keyword.BaiduKeywordAdapter()
    cookies = [{"name": "BAIDUID", "value": "no_bduss_here"}]
    try:
        adapter._assert_baidu_logged_in(cookies, resume_from=3)
    except RiskControlException as e:
        assert e.signal.layer == "auth"
        assert e.progress == 3
    else:
        raise AssertionError("expected RiskControlException")
```

The integration-level test above (`test_fetch_raises_auth_risk_control_when_not_logged_in`) covers the wiring of the helper into `_fetch_once`. These two tests pin down the helper's pure behavior so refactors can't silently break it.

- [ ] **Step 2: Run tests, verify FAIL**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_fetch_raises_auth_risk_control_when_not_logged_in tests/test_baidu_keyword.py::test_fetch_proceeds_when_logged_in -v`

Expected: FAIL — `_assert_baidu_logged_in` doesn't exist; `_fetch_once` doesn't have a BDUSS gate.

- [ ] **Step 3: Add the BDUSS gate to `_fetch_once`**

In `csm_core/monitor/platforms/baidu_keyword.py`, find the `BaiduKeywordAdapter` class and add the helper method (near the existing `_get_session` / `_drop_session` helpers, or right before `_fetch_once`):

```python
    def _assert_baidu_logged_in(self, cookies: list[dict[str, Any]], *, resume_from: int) -> None:
        """Raise RiskControlException(layer='auth') if BDUSS is missing.

        Caller passes the cookies it already read on the live persistent
        context. Keeping this a pure function makes it cheap to unit test.

        ``progress=resume_from`` so the runner's breakpoint bookkeeping
        (already_fetched + 1 == next-to-resume) stays consistent —
        nothing was fetched in this run; resume from the same index.
        """
        from ..drivers.risk_detector import RiskControlException, RiskSignal
        has_bduss = any(c.get("name") == "BDUSS" for c in cookies)
        if not has_bduss:
            raise RiskControlException(
                RiskSignal(layer="auth", detail="百度账号未登录或已过期，请到设置页登录"),
                progress=resume_from,
            )
```

Then find the `_fetch_once` body — specifically the line `with baidu_browser_session(headless=headless) as session:` (around line 835). Right **after** the `page = session.page` line (one or two lines below the `with`), insert:

```python
            # Login-state pre-flight: an anonymous fetch will burn quickly
            # against baidu 风控. Refuse fast and let the runner pause the
            # task + write a breakpoint; the UI shows "百度账号未登录" + a
            # "前往设置" button. Reusing the live context's cookies avoids
            # opening a second short-lived browser just to read BDUSS.
            cookies = session.context.cookies("https://www.baidu.com/")
            self._assert_baidu_logged_in(cookies, resume_from=resume_from)
```

(Adjust the indentation to match the surrounding `with` block. The existing code uses 4-space indent inside the `with`.)

- [ ] **Step 4: Run the auth tests, verify PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_fetch_raises_auth_risk_control_when_not_logged_in tests/test_baidu_keyword.py::test_fetch_proceeds_when_logged_in -v`

Expected: both PASS.

- [ ] **Step 5: Run the full baidu_keyword test file**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py -v`

Expected: all PASS. If a pre-existing `fetch`-level test fails because it didn't supply BDUSS in its FakeContext, update that test's FakeContext to return `[{"name": "BDUSS", "value": "x"}]`.

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): pre-flight BDUSS check in baidu_keyword fetch"
```

---

## Task 13: SERP post-check via `detect_login_required`

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

Covers the edge case where BDUSS is still in the cookie jar but baidu's server has already invalidated the session (so SERP redirects to wappass / passport).

- [ ] **Step 1: Add the failing test**

Append to `sidecar/tests/test_baidu_keyword.py`:

```python
def test_fetch_raises_auth_when_serp_redirects_to_login(monkeypatch):
    """BDUSS in cookies but SERP comes back as a wappass redirect →
    raise RiskControlException(layer='auth') with progress=kw_idx
    (so resume continues from this keyword, not from the start)."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    class FakeResp:
        def __init__(self, url: str):
            self.url = url

    class FakeContext:
        def cookies(self, url=None):
            return [{"name": "BDUSS", "value": "x"}]

    class FakePage:
        def goto(self, url, **kwargs):
            # baidu redirected SERP to the login wall
            return FakeResp("https://wappass.baidu.com/static/captcha/tuxing.html?...")
        def content(self):
            return ""

    class FakeSession:
        def __init__(self):
            self.page = FakePage()
            self.context = FakeContext()

    from contextlib import contextmanager
    @contextmanager
    def fake_session(*, headless, user_data_dir=None):
        yield FakeSession()

    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", fake_session)
    # Prevent _check_block + article fetches from running
    monkeypatch.setattr(baidu_keyword, "parse_serp", lambda html: {"default": [], "news": []})
    # Disable the article-level fetches and pacer so the test runs in <1s
    from csm_core.monitor import rate_limit
    monkeypatch.setattr(rate_limit, "get_pacer", lambda key: type(
        "P", (), {"wait": lambda self: None})())
    monkeypatch.setattr(rate_limit, "get_breaker", lambda key: type(
        "B", (), {"allow": lambda self: True,
                  "record_success": lambda self: None,
                  "record_failure": lambda self: None})())

    adapter = baidu_keyword.BaiduKeywordAdapter()
    task = MonitorTask(
        id=99, type="baidu_keyword",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keywords": ["aaa", "bbb"], "target_brand": "X"},
    )

    try:
        adapter.fetch(task, resume_from=0)
    except RiskControlException as e:
        assert e.signal.layer == "auth"
        assert e.progress == 0  # failed on first keyword
    else:
        raise AssertionError("expected RiskControlException(layer='auth')")
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_fetch_raises_auth_when_serp_redirects_to_login -v`

Expected: FAIL — the SERP goto returns a wappass response but `_fetch_once` doesn't check `detect_login_required` yet, so it tries to parse it as a regular SERP.

- [ ] **Step 3: Wire `detect_login_required` into `_fetch_once`**

Find the line in `_fetch_once` where `_navigate_to_serp(page, keyword)` is called inside the keyword loop. The current shape (post-Task 2) is roughly:

```python
            for rel_idx, keyword in enumerate(keywords_to_fetch):
                kw_idx = resume_from + rel_idx
                ...
                response = _navigate_to_serp(page, keyword)
                # 4-layer detect_risk follows here in the existing code
                ...
```

**Directly after** the `response = _navigate_to_serp(page, keyword)` line, **before** the existing `detect_risk(page, response)` block, insert:

```python
                # SERP-level login-wall check. Cookie may still be in the
                # jar but baidu's server-side session has expired and the
                # SERP redirects to wappass / passport / shows "请登录" body.
                # Raise auth risk_control so the runner pauses + writes a
                # breakpoint at this keyword index (resume continues here).
                from ..drivers.baidu_login import detect_login_required
                from ..drivers.risk_detector import RiskControlException, RiskSignal
                if detect_login_required(response, page):
                    raise RiskControlException(
                        RiskSignal(
                            layer="auth",
                            detail="登录态失效（SERP 跳转登录页），请到设置页重新登录",
                        ),
                        progress=kw_idx,
                    )
```

Pull the `from ..drivers.baidu_login import detect_login_required` up to the file's top-level imports if you prefer — there's already a `from ..drivers.baidu_browser import baidu_browser_session` at line 30, so adding the sibling import there is consistent.

- [ ] **Step 4: Run test, verify PASS**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_fetch_raises_auth_when_serp_redirects_to_login -v`

Expected: PASS.

- [ ] **Step 5: Run the full file**

Run: `cd sidecar && python -m pytest tests/test_baidu_keyword.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): SERP-level login wall check in baidu fetch"
```

---

## Task 14: BaiduRankingPage banner for `layer="auth"`

**Files:**
- Modify: `frontend/src/components/monitor/history/BaiduRankingPage.vue`

The Level 2 page already shows a generic risk_control banner (per the baidu-monitor-hardening-design spec). Add an `auth`-specific branch with a "前往设置" button.

- [ ] **Step 1: Locate the existing risk_control banner**

Run: `grep -n "captcha_signal_layer\|status === 'risk_control'\|risk_control" frontend/src/components/monitor/history/BaiduRankingPage.vue | head -20`

You're looking for a `<div>` in the template that conditionally renders when `latestResult?.status === 'risk_control'`. The exact line number will shift over time — the marker is the existing banner that mentions the captcha signal layer/detail. If the file has a single risk_control banner div, modify it. If it has multiple, find the one that's part of the Level 2 detail page (not a list-level toast).

- [ ] **Step 2: Add the auth branch**

In the existing risk_control banner, wrap its content with a `v-if`/`v-else` that splits on the `auth` layer. The exact structure depends on what's already there, but the pattern should look like:

```vue
<div
  v-if="latestResult?.status === 'risk_control'"
  class="mb-3 px-3 py-2 rounded text-[11.5px]"
  :style="{
    background: latestResult.metric?.captcha_signal_layer === 'auth'
      ? 'rgba(220, 38, 38, 0.08)'
      : 'rgba(238, 106, 42, 0.10)',
    color: 'var(--primary-deep)',
    borderLeft: latestResult.metric?.captcha_signal_layer === 'auth'
      ? '3px solid #dc2626'
      : '3px solid var(--primary)',
  }"
>
  <template v-if="latestResult.metric?.captcha_signal_layer === 'auth'">
    百度账号未登录或已过期。请到设置页重新登录后点「启动监测」从断点继续抓取。
    <router-link
      :to="{ name: 'settings', hash: '#baidu-account' }"
      class="ml-2 underline"
    >
      前往设置
    </router-link>
  </template>
  <template v-else>
    上次抓取被百度风控拦截
    （{{ latestResult.metric?.captcha_signal_layer }} / {{ latestResult.metric?.captcha_signal_detail }}）。
    断点位置：keyword #{{ latestResult.metric?.last_resumed_keyword ?? 0 }}。
    点击右下方「启动监测」可从断点继续。
  </template>
</div>
```

Notes:
- If the existing banner doesn't use `router-link` (e.g., the app uses a different navigation pattern), inspect what other "go to settings" links look like elsewhere in `SettingsView.vue` or `App.vue` and match that style.
- If there's no `id="baidu-account"` anchor in SettingsView yet, that's fine — the route will land on the settings page without scrolling. Adding an anchor is a follow-up cleanup; spec marked the SettingsRow location explicitly, you can add `id="baidu-account"` to the new SettingsRow wrapper in Task 11 if you want.

- [ ] **Step 3: Build + smoke**

Run: `cd frontend && npm run build`

Expected: PASS.

To smoke-test the UI: temporarily insert a fake `metric: {captcha_signal_layer: "auth"}` history record (or set the data through the dev sidecar's API) and confirm the auth banner renders. Or just verify visually in the dev stack after Task 15's real test triggers it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue
git commit -m "feat(frontend): show auth-specific banner when baidu task hits login wall"
```

---

## Task 15: Regression sweep + manual smoke

**Files:** none (verification only)

Final pass before declaring done.

- [ ] **Step 1: Run all backend tests**

Run: `cd sidecar && python -m pytest -x`

Expected: all PASS. If anything fails, investigate before declaring complete.

- [ ] **Step 2: Frontend build (includes vue-tsc)**

Run: `cd frontend && npm run build`

Expected: clean exit, vue-tsc reports no errors.

- [ ] **Step 3: Real-world smoke test (Tauri dev mode)**

Start the dev stack: `cd frontend && npm run tauri:dev` (or use `./dev.ps1` if present).

Sequence:
1. Open the app → Settings → 百度账号 section
2. Confirm "未登录" displays
3. Click "登录百度" → confirm dialog → OK → patchright window opens on www.baidu.com
4. Click the 登录 button in the patchright window → scan QR / username+password → complete login
5. patchright window closes automatically → toast 绿色「百度账号登录成功」
6. Settings row updates to "已登录" (possibly without username if passport API stub didn't fetch it — that's fine per spec)
7. Reset profile button: confirm it still works (click → cookies cleared → settings row goes back to "未登录")
8. Re-login
9. Go to monitor → create or run a baidu_keyword task (the 0519-4 task from the failed real-world test would be ideal: 10 keywords × vacuum-cleaner brand "CEWEY")
10. Watch the task run. Expected: all 10 keywords complete; logs should NOT contain `风控拦截` warnings; `default_results` populated; `content_preview` has real article text

Stop condition for success: the task completes without hitting `RiskControlException` at all (or at most 1-2 keywords, indicating the login is working).

- [ ] **Step 4: Negative smoke (force logged-out)**

While the task is finished and idle:
1. Click "重置百度浏览器 profile" → confirm → cookies wiped
2. Settings row goes back to "未登录"
3. Run any baidu_keyword task → it should immediately fail with `risk_control` status, `metric.captcha_signal_layer="auth"`, and the BaiduRankingPage Level 2 should show the auth banner with "前往设置" link

- [ ] **Step 5: Final commit (if any cleanup or doc tweaks landed)**

If steps 1-4 surfaced anything small worth fixing, fix and commit. Otherwise nothing to commit here — the task is verification.

```bash
git status  # confirm no uncommitted changes
```

- [ ] **Step 6: Branch is ready for PR**

The branch should now contain ~14 commits covering Tasks 1-14 + this final regression. Open a PR with the spec link in the body (`docs/superpowers/specs/2026-05-19-baidu-login-profile-design.md`). The PR title can match the spec's H1: `feat(monitor): baidu login + simplified SERP navigation`.

```bash
git status
git push -u origin claude/hopeful-elion-cff72a
gh pr create --title "feat(monitor): baidu login + simplified SERP navigation" --body "..."
```

(User has explicit preference: PR via gh, not local `git merge main`. See `feedback_merge_flow_pr.md` memory.)
