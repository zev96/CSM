"""Tests for interactive cookie capture — pure logic only.

The real flow opens a Patchright window and waits for human input,
which isn't testable in CI. We cover:
- Platform spec registry has the expected platforms
- ``_format_cookie_text`` matches the existing ``k=v; k=v`` shape
- Unknown platforms raise ValueError, not silently default
- Dedup behavior on cookie names
"""
from __future__ import annotations
import pytest

from csm_core.monitor.drivers import interactive_login
from csm_core.monitor.drivers.interactive_login import (
    LOGIN_SPECS,
    _format_cookie_text,
    capture_cookies_via_login,
)


class TestRegistry:
    def test_covers_all_four_monitored_platforms(self):
        """The 4 platforms the rest of the app supports must all be
        login-capturable. Otherwise we ship a partial feature where
        zhihu works but the user has to paste cookies for B 站."""
        assert set(LOGIN_SPECS.keys()) == {
            "zhihu_question",
            "bilibili_comment",
            "douyin_comment",
            "kuaishou_comment",
        }

    def test_zhihu_spec_uses_z_c0_as_success_marker(self):
        spec = LOGIN_SPECS["zhihu_question"]
        assert spec.success_cookie_name == "z_c0"
        assert spec.login_url.startswith("https://www.zhihu.com")
        assert "zhihu" in spec.cookie_domain

    def test_each_spec_has_required_fields(self):
        """Defensive — if someone adds a new platform spec without all
        fields the dataclass would already catch it, but explicit test
        documents the contract."""
        for name, spec in LOGIN_SPECS.items():
            assert spec.login_url.startswith("http"), name
            assert spec.success_cookie_name, name
            assert spec.cookie_domain, name
            assert spec.display_name, name


class TestUnknownPlatform:
    def test_raises_valueerror_with_supported_list(self):
        """Mistyped platform names should fail loudly so the bug is
        traceable in the API layer, not silently capture cookies under
        a wrong platform key."""
        with pytest.raises(ValueError) as exc:
            capture_cookies_via_login(platform="zhihu", label="x", timeout_s=10)
        # The supported list should be in the message for fast debug.
        assert "zhihu_question" in str(exc.value)


class TestFormatCookieText:
    def test_renders_k_eq_v_semicolon_separated(self):
        cookies = [
            {"name": "z_c0", "value": "abc", "domain": ".zhihu.com"},
            {"name": "q_c1", "value": "def", "domain": ".zhihu.com"},
        ]
        out = _format_cookie_text(cookies)
        assert out == "z_c0=abc; q_c1=def"

    def test_dedups_by_name(self):
        """zhihu sometimes returns the same cookie name on two different
        sub-domains (one host-only, one .zhihu.com). We keep the first
        one rather than emit duplicates that would break the
        ``k=v; k=v`` parser downstream."""
        cookies = [
            {"name": "z_c0", "value": "from-host-only", "domain": "www.zhihu.com"},
            {"name": "z_c0", "value": "from-wildcard", "domain": ".zhihu.com"},
        ]
        out = _format_cookie_text(cookies)
        assert out.count("z_c0=") == 1
        # Whichever ordering Playwright returned, we keep the first.
        assert "z_c0=from-host-only" in out

    def test_skips_empty_names(self):
        out = _format_cookie_text([
            {"name": "", "value": "garbage", "domain": ".zhihu.com"},
            {"name": "z_c0", "value": "real", "domain": ".zhihu.com"},
        ])
        assert out == "z_c0=real"

    def test_empty_input_returns_empty_string(self):
        assert _format_cookie_text([]) == ""

    def test_matches_existing_parse_format(self):
        """Round-trip: a captured cookie text should parse cleanly via
        the same ``_parse_cookies`` logic the zhihu adapter uses. If we
        emit something the parser chokes on, fast path breaks."""
        from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter
        out = _format_cookie_text([
            {"name": "z_c0", "value": "v1", "domain": ".zhihu.com"},
            {"name": "d_c0", "value": "v2|with|pipes", "domain": ".zhihu.com"},
            {"name": "_zap", "value": "v3", "domain": ".zhihu.com"},
        ])
        parsed = ZhihuQuestionAdapter._parse_cookies(out)
        assert parsed["z_c0"] == "v1"
        assert parsed["d_c0"] == "v2|with|pipes"
        assert parsed["_zap"] == "v3"
