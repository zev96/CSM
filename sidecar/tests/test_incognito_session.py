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
