"""mining_browser.launched_page must delegate to patchright_pool, not run its own launch_persistent_context."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from csm_core.browser_infra import mining_browser


class TestPoolDelegation:
    """After Task 6, mining_browser.launched_page should be a thin adapter over patchright_pool.
    Not its own launch_persistent_context."""

    def test_launched_page_goes_through_pool_acquire(self, monkeypatch):
        """The pool's acquire (get_page) must be called."""
        pool_calls = {"n": 0}

        def fake_pool_acquire(*args, **kwargs):
            pool_calls["n"] += 1
            page = MagicMock()
            # page.context must exist for _inject_monitor_cookies
            page.context = MagicMock()
            page.context.add_cookies = MagicMock()
            return page

        monkeypatch.setattr("csm_core.browser_infra.patchright_pool.get_page", fake_pool_acquire, raising=False)

        with mining_browser.launched_page("douyin", headless=False) as page:
            assert page is not None

        assert pool_calls["n"] >= 1, "patchright_pool.get_page should have been called"

    def test_launched_page_does_not_call_sync_playwright_directly(self, monkeypatch):
        """The refactor's contract: mining_browser MUST NOT run its own launch_persistent_context.
        Patching sync_playwright is a heavy-handed but sure way to catch that regression."""
        sync_pw_calls = {"n": 0}

        def fake_sync_pw():
            sync_pw_calls["n"] += 1
            raise RuntimeError("mining_browser should not call sync_playwright; pool should")

        # Patch the import path mining_browser uses
        monkeypatch.setattr("patchright.sync_api.sync_playwright", fake_sync_pw, raising=False)
        # Also patch the pool entry as in the test above so we have a working stub
        page_stub = MagicMock()
        page_stub.context = MagicMock()
        page_stub.context.add_cookies = MagicMock()
        monkeypatch.setattr("csm_core.browser_infra.patchright_pool.get_page", lambda *a, **k: page_stub, raising=False)

        with mining_browser.launched_page("douyin", headless=False) as page:
            pass

        assert sync_pw_calls["n"] == 0, "mining_browser must not call sync_playwright directly after Task 6"
