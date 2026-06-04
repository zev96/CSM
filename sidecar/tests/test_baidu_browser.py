"""Tests for baidu_browser.baidu_browser_session — persistent BrowserContext
contextmanager that replaces the old incognito_session.

These tests use monkey-patched fake playwright handles to avoid real
Chromium startup. The fakes mirror only the surface baidu_browser_session
actually uses.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ── Fakes ──────────────────────────────────────────────────────────────


class FakeContext:
    """Stand-in for patchright BrowserContext returned by
    launch_persistent_context. Records calls for assertions."""

    def __init__(self):
        self.pages: list[Any] = []
        self.close_called = False
        self._cookies_returned: list[dict[str, Any]] = []

    def new_page(self):
        page = object()
        self.pages.append(page)
        return page

    def close(self):
        self.close_called = True

    def cookies(self, url=None):
        return list(self._cookies_returned)


class FakeChromium:
    def __init__(self):
        self.last_user_data_dir: str | None = None
        self.last_kwargs: dict[str, Any] = {}
        self.context = FakeContext()
        self.executable_path: str | None = None  # overridden per-test

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.last_user_data_dir = user_data_dir
        self.last_kwargs = kwargs
        return self.context


class FakePW:
    def __init__(self):
        self.chromium = FakeChromium()
        self.stop_called = False

    def stop(self):
        self.stop_called = True


class FakeSyncPW:
    def __init__(self, pw: FakePW):
        self._pw = pw

    def start(self):
        return self._pw


@pytest.fixture
def fake_pw(monkeypatch):
    """Provide a FakePW, wire baidu_browser to use it."""
    from csm_core.monitor.drivers import baidu_browser

    pw = FakePW()
    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: FakeSyncPW(pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)
    return pw


# ── Tests ──────────────────────────────────────────────────────────────


def test_baidu_browser_session_uses_persistent_context(fake_pw, tmp_path):
    """Confirms launch_persistent_context is called with our user_data_dir
    + the right kwargs (headless honored, viewport, image-disabled blink flag)."""
    from csm_core.monitor.drivers import baidu_browser

    user_dir = tmp_path / "profile"
    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=user_dir) as sess:
        assert sess.page is not None
        assert sess.context is fake_pw.chromium.context

    chromium = fake_pw.chromium
    assert chromium.last_user_data_dir == str(user_dir)
    # headless=True is passed through verbatim (no longer downgraded — the
    # old "stealth needs headed" hack caused off-screen layout invalidation
    # which broke fill/click)
    assert chromium.last_kwargs["headless"] is True
    # viewport is propagated
    assert chromium.last_kwargs["viewport"] == {"width": 1366, "height": 768}
    # launch flags include the image-disabled blink flag (keeps SERP抓取轻量).
    # headless=True → no window → offscreen args must NOT be added.
    args = chromium.last_kwargs["args"]
    assert "--blink-settings=imagesEnabled=false" in args
    assert "--window-position=-32000,-32000" not in args
    assert "--disable-features=CalculateNativeWinOcclusion" not in args


def test_self_built_headed_hidden_has_offscreen_flags(fake_pw, tmp_path):
    """自建 profile + headless=False + hidden_window=True（默认）→
    args 应包含 --window-position=-32000,-32000 和反遮挡 flags。
    off-screen 已借助反遮挡 flags 重新启用（修复了历史上的 0×0 BoundingClientRect bug）。
    """
    from csm_core.monitor.drivers import baidu_browser

    with baidu_browser.baidu_browser_session(
        headless=False, user_data_dir=tmp_path / "p", hidden_window=True
    ):
        pass

    args = fake_pw.chromium.last_kwargs["args"]
    assert "--window-position=-32000,-32000" in args
    assert "--disable-features=CalculateNativeWinOcclusion" in args
    assert "--blink-settings=imagesEnabled=false" in args  # 自建 flag 不变


def test_self_built_headless_no_offscreen_flags(fake_pw, tmp_path):
    """自建 profile + headless=True → 无窗口 → offscreen args 不应存在。"""
    from csm_core.monitor.drivers import baidu_browser

    with baidu_browser.baidu_browser_session(
        headless=True, user_data_dir=tmp_path / "p"
    ):
        pass

    args = fake_pw.chromium.last_kwargs["args"]
    assert "--window-position=-32000,-32000" not in args
    assert "--disable-features=CalculateNativeWinOcclusion" not in args


def test_self_built_headed_hidden_window_false_no_offscreen_flags(fake_pw, tmp_path):
    """自建 profile + headless=False + hidden_window=False → 即使有头也不移屏外。"""
    from csm_core.monitor.drivers import baidu_browser

    with baidu_browser.baidu_browser_session(
        headless=False, user_data_dir=tmp_path / "p", hidden_window=False
    ):
        pass

    args = fake_pw.chromium.last_kwargs["args"]
    assert "--window-position=-32000,-32000" not in args
    assert "--disable-features=CalculateNativeWinOcclusion" not in args


def test_baidu_browser_session_closes_on_exit(fake_pw, tmp_path):
    """Verifies context.close + pw.stop run in the finally clause."""
    from csm_core.monitor.drivers import baidu_browser

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=tmp_path / "p"):
        pass

    assert fake_pw.chromium.context.close_called is True
    assert fake_pw.stop_called is True


def test_baidu_browser_session_creates_dir_if_missing(fake_pw, tmp_path):
    """user_data_dir is auto-created on first use (mkdir -p)."""
    from csm_core.monitor.drivers import baidu_browser

    target = tmp_path / "not_yet_created" / "profile"
    assert not target.exists()

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=target):
        pass

    assert target.exists()


def test_reset_profile_removes_dir(tmp_path):
    """reset_profile deletes the entire user_data_dir."""
    from csm_core.monitor.drivers import baidu_browser

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Default").mkdir()
    (profile / "Default" / "Cookies").write_text("fake cookie data")

    baidu_browser.reset_profile(user_data_dir=profile)

    assert not profile.exists()


def test_reset_profile_idempotent_on_missing_dir(tmp_path):
    """reset_profile is safe when called on a non-existent dir."""
    from csm_core.monitor.drivers import baidu_browser

    target = tmp_path / "does_not_exist"
    # Must not raise
    baidu_browser.reset_profile(user_data_dir=target)
    assert not target.exists()


def test_log_profile_health_fail_soft(fake_pw, tmp_path, caplog):
    """If context.cookies raises, baidu_browser_session still works.
    The log is non-fatal."""
    from csm_core.monitor.drivers import baidu_browser

    # Make cookies() raise so _log_profile_health hits the except branch
    def boom(url=None):
        raise RuntimeError("simulated cookie-jar error")
    fake_pw.chromium.context.cookies = boom

    # Should NOT raise
    with caplog.at_level("DEBUG", logger="csm_core.monitor.drivers.baidu_browser"):
        with baidu_browser.baidu_browser_session(headless=True, user_data_dir=tmp_path / "p"):
            pass

    assert "profile health log failed" in caplog.text


def test_baidu_browser_session_native_mode_uses_chrome_channel(monkeypatch, tmp_path):
    """use_native_chrome=True 时：launch_persistent_context 拿到 channel='chrome'
    + executable_path + --profile-directory，且 headless 被强制改成 False。
    """
    from csm_core.monitor.drivers import baidu_browser

    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.pages = [MagicMock()]
    fake_context.cookies.return_value = []
    fake_chromium = MagicMock()
    fake_chromium.launch_persistent_context = lambda **kw: (captured.update(kw), fake_context)[1]
    fake_pw = MagicMock()
    fake_pw.chromium = fake_chromium

    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: MagicMock(start=lambda: fake_pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=True,  # 应该被强制覆盖为 False
        user_data_dir=tmp_path,
        use_native_chrome=True,
        chrome_executable_path="C:/test/chrome.exe",
        chrome_profile_name="Profile 1",
    ):
        pass

    assert captured.get("channel") == "chrome"
    assert captured.get("executable_path") == "C:/test/chrome.exe"
    assert captured.get("headless") is False  # native 强制 False
    args = captured.get("args") or []
    assert "--profile-directory=Profile 1" in args
    # native mode 不加 --blink-settings=imagesEnabled=false
    assert "--blink-settings=imagesEnabled=false" not in args
    # native 永远有头；默认 hidden_window=True → 必须含移屏外+反遮挡 flags
    assert "--window-position=-32000,-32000" in args
    assert "--disable-features=CalculateNativeWinOcclusion" in args


def test_baidu_browser_session_self_built_mode_unchanged(monkeypatch, tmp_path):
    """use_native_chrome=False（默认）：不带 channel；自建模式传 executable_path
    （完整 Chromium，绕开 chrome-headless-shell 缺失）。"""
    from csm_core.monitor.drivers import baidu_browser

    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.pages = [MagicMock()]
    fake_context.cookies.return_value = []
    fake_chromium = MagicMock()
    fake_chromium.launch_persistent_context = lambda **kw: (captured.update(kw), fake_context)[1]
    fake_pw = MagicMock()
    fake_pw.chromium = fake_chromium

    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: MagicMock(start=lambda: fake_pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=True,
        user_data_dir=tmp_path,
    ):
        pass

    assert "channel" not in captured
    # 自建模式现在传 executable_path（完整 Chromium，绕开 headless-shell 缺失）
    assert "executable_path" in captured
    assert captured.get("headless") is True
    args = captured.get("args") or []
    assert "--blink-settings=imagesEnabled=false" in args  # 自建保留


def test_self_built_headless_passes_executable_path(monkeypatch, tmp_path):
    """自建 profile + headless=True 抓取也要传完整 Chromium executable_path，
    否则同样撞 chrome-headless-shell 缺失（默认 headless 抓取会挂）。"""
    from csm_core.monitor.drivers import baidu_browser
    pw = FakePW()
    pw.chromium.executable_path = r"C:\fake\chromium\chrome.exe"  # 加到 FakeChromium
    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: FakeSyncPW(pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=tmp_path):
        pass
    assert pw.chromium.last_kwargs.get("executable_path") == r"C:\fake\chromium\chrome.exe"
    assert pw.chromium.last_kwargs.get("headless") is True


def test_baidu_browser_session_native_prunes_caches_on_exit(monkeypatch, tmp_path):
    """native 模式：session 退出（Chrome 已关）后清理副本缓存，保留登录态。"""
    from csm_core.monitor.drivers import baidu_browser

    copy = tmp_path  # 充当副本根
    default = copy / "Default"
    default.mkdir()
    (default / "Service Worker").mkdir()
    (default / "Service Worker" / "x").write_bytes(b"cache" * 200)
    (default / "Network").mkdir()
    (default / "Network" / "Cookies").write_bytes(b"login")

    fake_context = MagicMock()
    fake_context.pages = [MagicMock()]
    fake_context.cookies.return_value = []
    fake_chromium = MagicMock()
    fake_chromium.launch_persistent_context = lambda **kw: fake_context
    fake_pw = MagicMock()
    fake_pw.chromium = fake_chromium
    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: MagicMock(start=lambda: fake_pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=False,
        user_data_dir=copy,
        use_native_chrome=True,
        chrome_executable_path="C:/test/chrome.exe",
        chrome_profile_name="Default",
    ):
        pass

    # 缓存被清，登录态保留
    assert not (default / "Service Worker").exists()
    assert (default / "Network" / "Cookies").exists()


def test_baidu_browser_session_self_built_does_not_prune(fake_pw, tmp_path):
    """自建 profile 模式：不清缓存（prune 只针对 native 副本）。"""
    from csm_core.monitor.drivers import baidu_browser

    profile = tmp_path / "p"
    profile.mkdir()
    (profile / "Service Worker").mkdir()
    (profile / "Service Worker" / "x").write_bytes(b"cache")

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=profile):
        pass

    # 自建模式缓存原样保留
    assert (profile / "Service Worker").exists()
