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


# ── Task 1: get_login_status passes full Chromium executable_path ───────


class _FakeCtxForExe:
    def __init__(self, cookies): self._c = cookies; self.closed = False
    def cookies(self, url=None): return list(self._c)
    def close(self): self.closed = True

class _FakeChromiumForExe:
    executable_path = r"C:\fake\chromium\chrome.exe"
    def __init__(self, cookies):
        self.last_kwargs = {}
        self._ctx = _FakeCtxForExe(cookies)
    def launch_persistent_context(self, **kwargs):
        self.last_kwargs = kwargs
        return self._ctx

class _FakePWForExe:
    def __init__(self, cookies): self.chromium = _FakeChromiumForExe(cookies)
    def stop(self): pass

class _FakeSyncForExe:
    def __init__(self, pw): self._pw = pw
    def start(self): return self._pw


def test_get_login_status_passes_full_chromium_executable(monkeypatch, tmp_path):
    """headless 状态读取必须显式传完整 Chromium 的 executable_path，
    否则 Patchright 去找未随包的 chrome-headless-shell 启动失败。"""
    bduss = {"name": "BDUSS", "value": "x", "expires": -1}
    pw = _FakePWForExe([bduss])
    monkeypatch.setattr(
        "csm_core.monitor.drivers.baidu_login._sync_playwright",
        lambda: _FakeSyncForExe(pw),
    )
    monkeypatch.setattr(
        "csm_core.monitor.drivers.baidu_login.ensure_browsers_path", lambda: None,
    )
    from csm_core.monitor.drivers import baidu_login
    status = baidu_login.get_login_status(user_data_dir=tmp_path)

    assert pw.chromium.last_kwargs.get("executable_path") == r"C:\fake\chromium\chrome.exe"
    assert pw.chromium.last_kwargs.get("headless") is True
    assert status["logged_in"] is True
