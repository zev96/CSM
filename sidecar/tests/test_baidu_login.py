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
