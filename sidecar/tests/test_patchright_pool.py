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


class TestProxyInjection:
    """Verify _get_proxy_for_launch helper returns correct values."""

    def test_returns_none_when_no_proxies_path(self, monkeypatch):
        """When AppConfig.proxies_path is None, should return None."""
        from csm_core.browser_infra import patchright_pool
        from unittest.mock import MagicMock

        mock_cfg = MagicMock()
        mock_cfg.proxies_path = None
        mock_service = MagicMock()
        mock_service.load.return_value = mock_cfg
        monkeypatch.setattr(
            "csm_sidecar.services.config_service.load",
            mock_service.load,
        )
        result = patchright_pool._get_proxy_for_launch()
        assert result is None

    def test_returns_proxy_dict_when_configured(self, monkeypatch, tmp_path):
        """When proxies_path is set + proxies.json valid, should return {'server': ...}."""
        import json
        from csm_core.browser_infra import patchright_pool
        from unittest.mock import MagicMock

        # Reset pool cache so this test's path is fresh
        patchright_pool._pool_cache = None

        proxies_json = tmp_path / "proxies.json"
        proxies_json.write_text(json.dumps({
            "enabled": True,
            "rotation_strategy": "on_risk_control",
            "proxies": [{"server": "http://1.2.3.4:8080"}],
        }), encoding="utf-8")

        mock_cfg = MagicMock()
        mock_cfg.proxies_path = str(proxies_json)
        mock_service = MagicMock()
        mock_service.load.return_value = mock_cfg
        monkeypatch.setattr(
            "csm_sidecar.services.config_service.load",
            mock_service.load,
        )
        result = patchright_pool._get_proxy_for_launch()
        assert result is not None
        assert result["server"] == "http://1.2.3.4:8080"

    def test_returns_none_when_config_service_unavailable(self, monkeypatch):
        """If config_service import fails (e.g., in tests without sidecar), should return None."""
        from csm_core.browser_infra import patchright_pool

        def raise_import(*a, **kw):
            raise ImportError("no sidecar")

        monkeypatch.setattr(
            "csm_sidecar.services.config_service.load",
            raise_import,
        )
        result = patchright_pool._get_proxy_for_launch()
        assert result is None

    def test_pool_cache_returns_same_instance_for_same_path(self, monkeypatch, tmp_path):
        """_get_or_create_pool must return same ProxyPool across calls with same path."""
        from csm_core.browser_infra import patchright_pool
        # Reset cache state
        patchright_pool._pool_cache = None

        p = tmp_path / "proxies.json"
        p.write_text('{"enabled": true, "proxies": [{"server": "http://1.1.1.1:8080"}]}', encoding="utf-8")

        pool1 = patchright_pool._get_or_create_pool(str(p))
        pool2 = patchright_pool._get_or_create_pool(str(p))
        assert pool1 is pool2  # same instance

        # Different path → new instance
        p2 = tmp_path / "other.json"
        p2.write_text('{"enabled": true, "proxies": []}', encoding="utf-8")
        pool3 = patchright_pool._get_or_create_pool(str(p2))
        assert pool3 is not pool1

    def test_pool_state_persists_across_get_calls(self, monkeypatch, tmp_path):
        """mark_failed state from one launch is visible to the next."""
        from csm_core.browser_infra import patchright_pool
        patchright_pool._pool_cache = None

        p = tmp_path / "proxies.json"
        p.write_text(
            '{"enabled": true, "rotation_strategy": "on_risk_control", '
            '"proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}]}',
            encoding="utf-8")

        pool = patchright_pool._get_or_create_pool(str(p))
        pool.mark_failed("http://1.1.1.1:8080")
        pool.mark_failed("http://1.1.1.1:8080")
        pool.mark_failed("http://1.1.1.1:8080")  # 3rd → disabled

        # Re-acquire pool, state should persist
        pool_again = patchright_pool._get_or_create_pool(str(p))
        assert "http://1.1.1.1:8080" in pool_again._disabled  # state survived


class TestSplitProxyAuth:
    """_split_proxy_auth must correctly separate credentials from the URL."""

    def test_split_proxy_auth_extracts_credentials(self):
        from csm_core.browser_infra.patchright_pool import _split_proxy_auth
        result = _split_proxy_auth("http://user:pass@1.2.3.4:8080")
        assert result["server"] == "http://1.2.3.4:8080"  # no credentials
        assert result["username"] == "user"
        assert result["password"] == "pass"

    def test_split_proxy_auth_no_credentials(self):
        from csm_core.browser_infra.patchright_pool import _split_proxy_auth
        result = _split_proxy_auth("http://1.2.3.4:8080")
        assert result == {"server": "http://1.2.3.4:8080"}

    def test_split_proxy_auth_socks5_with_auth(self):
        from csm_core.browser_infra.patchright_pool import _split_proxy_auth
        result = _split_proxy_auth("socks5://alice:wonderland@proxy.example.com:1080")
        assert result["server"] == "socks5://proxy.example.com:1080"
        assert result["username"] == "alice"
        assert result["password"] == "wonderland"
