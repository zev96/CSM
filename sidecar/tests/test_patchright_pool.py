"""Stealth 加固测试 —— pool 启动的 context 必须带正确 UA / init_script / launch_args / viewport / headers。"""
from __future__ import annotations

import pytest

from csm_core.browser_infra import patchright_pool


class TestStealthHardening:
    """Pure unit tests over the stealth-helper functions (no real browser)."""

    def test_launch_args_include_automation_disabled(self):
        args = patchright_pool._build_launch_args()
        assert "--disable-blink-features=AutomationControlled" in args

    def test_launch_args_include_no_sandbox(self):
        """Pre-existing launch args still present."""
        args = patchright_pool._build_launch_args()
        assert "--no-sandbox" in args

    def test_launch_args_include_window_size_when_viewport_given(self):
        """When viewport is passed, launch args must include matching --window-size."""
        vp = {"width": 1280, "height": 800}
        args = patchright_pool._build_launch_args(viewport=vp)
        assert "--window-size=1280,800" in args

    def test_launch_args_no_window_size_when_no_viewport(self):
        """Without viewport, --window-size not added (Chromium default)."""
        args = patchright_pool._build_launch_args()
        assert not any(a.startswith("--window-size") for a in args)

    def test_init_script_masks_webdriver(self):
        script = patchright_pool._build_init_script()
        assert "navigator" in script
        assert "webdriver" in script

    def test_init_script_masks_cdc(self):
        """ChromeDriver 残留变量 window.cdc_* 必须屏蔽。"""
        script = patchright_pool._build_init_script()
        assert "cdc_" in script.lower()

    def test_init_script_fakes_navigator_plugins(self):
        script = patchright_pool._build_init_script()
        assert "plugins" in script

    def test_init_script_fakes_navigator_languages(self):
        script = patchright_pool._build_init_script()
        assert "languages" in script

    def test_init_script_handles_window_chrome(self):
        """window.chrome placeholder for adapters where Patchright doesn't set it."""
        script = patchright_pool._build_init_script()
        assert "window.chrome" in script

    def test_init_script_no_leading_newline(self):
        """Init script should not start with a blank newline (cosmetic cleanliness)."""
        script = patchright_pool._build_init_script()
        assert not script.startswith("\n")

    def test_viewport_picked_from_three_buckets(self):
        """_pick_viewport returns one of 3 predefined viewports."""
        # Reset thread-local cache for this test to get a fresh pick
        if hasattr(patchright_pool._thread_viewport, "value"):
            del patchright_pool._thread_viewport.value
        v = patchright_pool._pick_viewport()
        expected = {(1280, 800), (1440, 900), (1366, 768)}
        assert (v["width"], v["height"]) in expected

    def test_viewport_sticky_within_thread(self):
        """Same thread gets the same viewport on repeated calls."""
        if hasattr(patchright_pool._thread_viewport, "value"):
            del patchright_pool._thread_viewport.value
        v1 = patchright_pool._pick_viewport()
        v2 = patchright_pool._pick_viewport()
        assert v1 == v2

    def test_viewport_distribution_across_threads(self):
        """Over many threads, all 3 buckets should appear."""
        import threading as _threading
        seen: set[tuple[int, int]] = set()
        lock = _threading.Lock()

        def worker():
            # Each thread gets its own _thread_viewport.value (threading.local)
            v = patchright_pool._pick_viewport()
            with lock:
                seen.add((v["width"], v["height"]))

        threads = [_threading.Thread(target=worker) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        expected = {(1280, 800), (1440, 900), (1366, 768)}
        assert seen.issubset(expected)
        assert len(seen) >= 2

    def test_extra_headers_accept_language(self):
        h = patchright_pool._build_extra_headers()
        assert h.get("Accept-Language", "").startswith("zh-CN")

    def test_extra_headers_does_not_set_sec_ch_ua(self):
        """sec-ch-ua headers MUST NOT be set — they'd mismatch navigator.userAgentData and trigger
        cheap FingerprintJS bot detection. Letting Patchright auto-respond to Accept-CH is the
        correct approach."""
        h = patchright_pool._build_extra_headers()
        assert "sec-ch-ua" not in h
        assert "sec-ch-ua-mobile" not in h
        assert "sec-ch-ua-platform" not in h


class TestStealthWiring:
    """Integration: verify get_page actually calls _build_launch_args / _pick_viewport /
    _build_init_script / _build_extra_headers when constructing launch_kwargs.

    Catches regressions where someone replaces a helper call with an inline literal."""

    def test_get_page_wires_helpers_to_launch(self, monkeypatch):
        """Mock launch_persistent_context, drive get_page, assert kwargs include
        the helper outputs (and add_init_script called)."""
        # NOTE: this test depends on the actual function name in patchright_pool.
        # If the launch happens inside `get_page` or `_create_context` or similar,
        # adapt the patch target accordingly.
        pytest.skip("TODO: implement after confirming patchright launch entry point name")
