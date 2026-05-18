"""Stealth 加固测试 —— pool 启动的 context 必须带正确 UA / init_script / launch_args / viewport / headers。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

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

    def test_viewport_randomization_three_buckets(self):
        """_pick_viewport() must return one of three predefined viewports."""
        seen = set()
        for _ in range(50):
            v = patchright_pool._pick_viewport()
            seen.add((v["width"], v["height"]))
        expected = {(1280, 800), (1440, 900), (1366, 768)}
        assert seen.issubset(expected)
        assert len(seen) >= 2  # 50 trials should see at least 2 buckets

    def test_extra_headers_accept_language(self):
        h = patchright_pool._build_extra_headers()
        assert h.get("Accept-Language", "").startswith("zh-CN")

    def test_extra_headers_sec_ch_ua(self):
        h = patchright_pool._build_extra_headers()
        assert "sec-ch-ua" in h
        assert "Chromium" in h["sec-ch-ua"]

    def test_extra_headers_sec_ch_ua_platform(self):
        h = patchright_pool._build_extra_headers()
        assert h.get("sec-ch-ua-platform") == '"Windows"'

    def test_extra_headers_sec_ch_ua_mobile(self):
        h = patchright_pool._build_extra_headers()
        assert h.get("sec-ch-ua-mobile") == "?0"
