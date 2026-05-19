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
