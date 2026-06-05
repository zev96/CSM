"""Tests that launched_page forwards offscreen args when hidden_window=True
and leaves launch args unchanged when hidden_window=False (mining default).

Uses the same fake-playwright monkeypatch pattern as test_baidu_browser.py:
a FakeSyncPW / FakeChromium pair records the args passed to
launch_persistent_context without ever starting a real Chromium process.

Monkeypatch seam: mining_browser.launched_page does
    from patchright.sync_api import sync_playwright
inside the function body, so we patch patchright.sync_api.sync_playwright
(which mining_browser's local import resolves at call time).

We also no-op ensure_browsers_path and _kill_process_tree (both imported at
module level in mining_browser) and configure_profile_root so _profile_dir_for
returns a real tmp dir instead of raising RuntimeError.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest


# ── Fakes ──────────────────────────────────────────────────────────────


class FakeContext:
    """Minimal stand-in for patchright BrowserContext."""

    def __init__(self):
        self.pages: list[Any] = []
        self.close_called = False

    def new_page(self):
        page = MagicMock()
        self.pages.append(page)
        return page

    def close(self):
        self.close_called = True

    def add_cookies(self, cookies):
        pass


class FakeChromium:
    def __init__(self):
        self.last_user_data_dir: str | None = None
        self.last_kwargs: dict[str, Any] = {}
        self.context = FakeContext()

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.last_user_data_dir = user_data_dir
        self.last_kwargs = kwargs
        return self.context


class FakePW:
    def __init__(self):
        self.chromium = FakeChromium()
        self.stop_called = False
        # mining_browser reads pw._impl_obj._connection._transport._proc.pid
        # Provide a stub so node_pid extraction succeeds (returns 0 via
        # attribute chain, which suppresses the kill call).
        self._impl_obj = MagicMock()
        self._impl_obj._connection._transport._proc.pid = 0

    def stop(self):
        self.stop_called = True


class FakeSyncPW:
    def __init__(self, pw: FakePW):
        self._pw = pw

    def start(self):
        return self._pw


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_pw(monkeypatch, tmp_path):
    """Provide a FakePW and wire mining_browser to use it.

    Patches:
    - patchright.sync_api.sync_playwright → FakeSyncPW
    - mining_browser.ensure_browsers_path → no-op
    - mining_browser._kill_process_tree → no-op
    - configure_profile_root(tmp_path) so _profile_dir_for works
    """
    import csm_core.browser_infra.mining_browser as mb

    pw = FakePW()

    # Patch patchright.sync_api.sync_playwright so that launched_page's
    # local "from patchright.sync_api import sync_playwright" resolves to
    # our fake. We must ensure the module is in sys.modules first.
    import importlib
    patchright_sync = importlib.import_module("patchright.sync_api")
    monkeypatch.setattr(patchright_sync, "sync_playwright", lambda: FakeSyncPW(pw))

    # No-op the OS-level helpers (imported at module top).
    monkeypatch.setattr(mb, "ensure_browsers_path", lambda: None)
    monkeypatch.setattr(mb, "_kill_process_tree", lambda pid, label=None: None)

    # Configure a real profile root so _profile_dir_for doesn't raise.
    mb.configure_profile_root(tmp_path / "profiles")

    return pw


# ── Tests ──────────────────────────────────────────────────────────────


def test_launched_page_offscreen_when_hidden(fake_pw):
    """hidden_window=True → offscreen + anti-occlusion flags in launch args."""
    from csm_core.browser_infra.mining_browser import launched_page

    with launched_page("geo_deepseek", hidden_window=True):
        pass

    recorded_args = fake_pw.chromium.last_kwargs.get("args", [])
    assert "--window-position=-32000,-32000" in recorded_args
    assert "--disable-features=CalculateNativeWinOcclusion" in recorded_args


def test_launched_page_no_offscreen_by_default(fake_pw):
    """hidden_window omitted (default False) → no offscreen args (mining unchanged)."""
    from csm_core.browser_infra.mining_browser import launched_page

    with launched_page("douyin"):
        pass

    recorded_args = fake_pw.chromium.last_kwargs.get("args", [])
    assert "--window-position=-32000,-32000" not in recorded_args
    assert "--disable-features=CalculateNativeWinOcclusion" not in recorded_args
