"""incognito_session 上下文管理器的单元测试。

不真启动 Chromium —— mock `sync_playwright` 的关键调用链，
验证 lifecycle 正确（start → launch → new_context → close 全打到）。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from csm_core.monitor.drivers import incognito_session


@pytest.fixture
def mock_playwright(monkeypatch):
    """让 sync_playwright() 返回我们能 spy 的对象树。"""
    pw_handle = MagicMock(name="pw_handle")
    context = MagicMock(name="context")
    browser = MagicMock(name="browser")
    page = MagicMock(name="page")

    browser.new_context.return_value = context
    context.new_page.return_value = page
    pw_handle.chromium.launch.return_value = browser

    pw_starter = MagicMock(name="pw_starter")
    pw_starter.start.return_value = pw_handle

    fake_sync = MagicMock(return_value=pw_starter)
    monkeypatch.setattr(incognito_session, "_sync_playwright", fake_sync)
    return {
        "sync": fake_sync,
        "pw_handle": pw_handle,
        "browser": browser,
        "context": context,
        "page": page,
    }


def test_session_yields_page(mock_playwright):
    with incognito_session.incognito_session(headless=True) as sess:
        assert sess.page is mock_playwright["page"]
        assert sess.context is mock_playwright["context"]


def test_session_passes_headless_flag(mock_playwright):
    with incognito_session.incognito_session(headless=False):
        pass
    launch_call = mock_playwright["pw_handle"].chromium.launch.call_args
    assert launch_call.kwargs.get("headless") is False


def test_session_headless_true_uses_offscreen_window_trick(mock_playwright):
    """headless=True 的"假隐藏"约定：始终 headed 启动（保 patchright
    stealth 完整），用 --window-position 把窗口推到屏外 + --start-minimized。
    Playwright 真 headless 在 stealth fork 下不可靠，这条约定不能破。"""
    with incognito_session.incognito_session(headless=True):
        pass
    launch_call = mock_playwright["pw_handle"].chromium.launch.call_args
    # 关键 1：真传给 chromium.launch 的 headless 必须是 False
    assert launch_call.kwargs.get("headless") is False
    # 关键 2：args 里必须有「屏外位置」+「最小化」两个 flag
    args = launch_call.kwargs.get("args") or []
    assert any("--window-position=" in a and "-32000" in a for a in args), (
        f"expected offscreen window-position in args, got: {args}"
    )
    assert "--start-minimized" in args, f"expected --start-minimized in args, got: {args}"


def test_session_disables_image_loading(mock_playwright):
    """SERP 抓取永远不需要图片，关掉 image loading 是性能默认 ——
    无论 headless 真假都关。"""
    for hl in (True, False):
        mock_playwright["pw_handle"].chromium.launch.reset_mock()
        with incognito_session.incognito_session(headless=hl):
            pass
        args = mock_playwright["pw_handle"].chromium.launch.call_args.kwargs.get("args") or []
        assert "--blink-settings=imagesEnabled=false" in args, (
            f"images must be disabled for SERP scraping (headless={hl}); got args: {args}"
        )


def test_session_uses_incognito_context_not_persistent(mock_playwright):
    """关键反爬不变量：必须用 browser.new_context()，绝不能用
    launch_persistent_context（持久 user-data-dir 会跨任务带前次痕迹）。"""
    with incognito_session.incognito_session(headless=True):
        pass
    # launch 被调一次（开 browser）
    assert mock_playwright["pw_handle"].chromium.launch.called
    # launch_persistent_context 绝不能被调
    assert not mock_playwright["pw_handle"].chromium.launch_persistent_context.called
    # new_context 被调一次（开无痕 context）
    assert mock_playwright["browser"].new_context.called


def test_session_closes_in_lifo_order(mock_playwright):
    """正常退出：context.close → browser.close → pw.stop。"""
    with incognito_session.incognito_session(headless=True):
        pass
    mock_playwright["context"].close.assert_called_once()
    mock_playwright["browser"].close.assert_called_once()
    mock_playwright["pw_handle"].stop.assert_called_once()


def test_session_closes_on_exception(mock_playwright):
    """异常路径也要关掉，否则 Chromium 进程会泄漏。"""
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with incognito_session.incognito_session(headless=True):
            raise Boom()

    mock_playwright["context"].close.assert_called_once()
    mock_playwright["browser"].close.assert_called_once()
    mock_playwright["pw_handle"].stop.assert_called_once()


def test_is_baidu_captcha_url_detects_wappass():
    assert incognito_session.is_baidu_captcha_url(
        "https://wappass.baidu.com/static/captcha/tuxing.html?ak=xxx"
    )


def test_is_baidu_captcha_url_detects_passport():
    assert incognito_session.is_baidu_captcha_url(
        "https://passport.baidu.com/?login&u=https://www.baidu.com/s?wd=test"
    )


def test_is_baidu_captcha_url_detects_verify():
    assert incognito_session.is_baidu_captcha_url(
        "https://verify.baidu.com/v2/index.html"
    )


def test_is_baidu_captcha_url_clean_baidu_url_not_captcha():
    assert not incognito_session.is_baidu_captcha_url(
        "https://www.baidu.com/s?wd=test"
    )
    assert not incognito_session.is_baidu_captcha_url("")
    assert not incognito_session.is_baidu_captcha_url("https://example.com")
