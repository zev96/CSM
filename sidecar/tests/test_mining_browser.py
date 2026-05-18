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

    def test_module_source_does_not_use_direct_playwright(self):
        """Regression guard: mining_browser.py must NOT contain launch_persistent_context
        or sync_playwright (Task 6 moved these to patchright_pool). A source-text check is
        more reliable than monkeypatching after-the-fact imports."""
        import pathlib
        src = pathlib.Path(mining_browser.__file__).read_text(encoding="utf-8")
        assert "launch_persistent_context" not in src, (
            "mining_browser must not call launch_persistent_context directly after Task 6"
        )
        assert "sync_playwright" not in src, (
            "mining_browser must not call sync_playwright directly after Task 6"
        )


class TestKeepAlive:
    """keep_alive=True must spawn a daemon that bumps pool.last_used so the reaper
    doesn't kill the browser during long-blocking workflows like interactive login."""

    def test_keep_alive_starts_bumper_thread(self, monkeypatch):
        """When keep_alive=True, a daemon thread named mining_keepalive_* is started."""
        import threading as _threading

        page_stub = MagicMock()
        page_stub.context = MagicMock()
        page_stub.context.add_cookies = MagicMock()
        monkeypatch.setattr(
            "csm_core.browser_infra.patchright_pool.get_page",
            lambda *a, **k: page_stub,
            raising=False,
        )
        bump_calls = {"n": 0}

        def fake_touch():
            bump_calls["n"] += 1

        monkeypatch.setattr(
            "csm_core.browser_infra.patchright_pool.touch_last_used",
            fake_touch,
            raising=False,
        )

        import time as _time

        with mining_browser.launched_page("douyin", keep_alive=True) as page:
            # Allow a brief moment for the daemon to start
            _time.sleep(0.05)
            alive_names = [t.name for t in _threading.enumerate()]
            assert any(n.startswith("mining_keepalive_") for n in alive_names), (
                "keep_alive=True should have started a mining_keepalive_* daemon thread"
            )

        # After context exit the stop_event is set; primary assertion: no crash
        assert page is not None

    def test_keep_alive_default_false_no_bumper(self, monkeypatch):
        """Without keep_alive=True, no mining_keepalive_* daemon thread is spawned."""
        import threading as _threading

        page_stub = MagicMock()
        page_stub.context = MagicMock()
        page_stub.context.add_cookies = MagicMock()
        monkeypatch.setattr(
            "csm_core.browser_infra.patchright_pool.get_page",
            lambda *a, **k: page_stub,
            raising=False,
        )

        before = {t.name for t in _threading.enumerate() if t.name.startswith("mining_keepalive")}

        with mining_browser.launched_page("douyin") as page:
            pass  # default keep_alive=False

        after = {t.name for t in _threading.enumerate() if t.name.startswith("mining_keepalive")}
        new_threads = after - before
        assert len(new_threads) == 0, f"no new keep-alive thread expected, got: {new_threads}"
