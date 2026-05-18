"""Tests for csm_core.monitor.drivers.risk_detector — 4 层风控信号融合。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from csm_core.monitor.drivers.risk_detector import (
    RiskSignal,
    detect_risk_by_url,
    detect_risk_by_dom,
    detect_risk_by_text,
    detect_risk_by_http,
    detect_risk,
)


# ── Layer 1: URL pattern ──────────────────────────────────────────────────
class TestUrlLayer:
    @pytest.mark.parametrize("url", [
        "https://wappass.baidu.com/static/captcha/index.html",
        "https://passport.baidu.com/v2/?login",
        "https://passport.baidu.com/?login&u=https%3A%2F%2Fwww.baidu.com",  # 老 marker 覆盖
        "https://verify.baidu.com/v2/index.html",                          # 老 marker 覆盖
        "https://baijiahao.baidu.com/safetycheck?id=123",
        "https://mbd.baidu.com/safe?token=abc",
        "https://www.baidu.com/captcha?from=serp",
    ])
    def test_known_captcha_url_patterns(self, url: str):
        sig = detect_risk_by_url(url)
        assert sig is not None
        assert sig.layer == "url"

    @pytest.mark.parametrize("url", [
        "https://www.baidu.com/s?wd=test",
        "https://baijiahao.baidu.com/s?id=12345",
        "https://www.zhihu.com/question/123",
    ])
    def test_normal_urls_pass(self, url: str):
        assert detect_risk_by_url(url) is None


class TestDomLayer:
    """DOM 层基于 Patchright Page.locator() 检测。用 MagicMock 模拟 page。"""

    @pytest.mark.parametrize("selector", [
        "#captcha-mask",
        ".passmod",
        '[id^="wappass"]',
        ".security-check",
        ".mod-error",
        ".error-page",
    ])
    def test_dom_selector_match(self, selector: str):
        page = MagicMock()
        def fake_locator(sel: str):
            mock_loc = MagicMock()
            mock_loc.count.return_value = 1 if sel == selector else 0
            return mock_loc
        page.locator = fake_locator
        sig = detect_risk_by_dom(page)
        assert sig is not None
        assert sig.layer == "dom"
        assert selector in sig.detail

    def test_dom_no_match(self):
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        assert detect_risk_by_dom(page) is None

    def test_dom_locator_error_swallowed(self):
        """page 还没 navigate / 被关闭等异常情况 detect 不应抛。"""
        page = MagicMock()
        page.locator = MagicMock(side_effect=RuntimeError("page closed"))
        assert detect_risk_by_dom(page) is None


class TestTextLayer:
    @pytest.mark.parametrize("text", [
        "请完成验证后继续访问",
        "页面包含 验证码 提示",
        "网络异常，请稍后重试",
        "系统繁忙，请稍后再试",
        "为了您的账号安全 请进行 安全验证",
    ])
    def test_text_phrase_match(self, text: str):
        sig = detect_risk_by_text(text)
        assert sig is not None
        assert sig.layer == "text"
        # 确认 detail 里带上了实际命中的短语，前端 toast 才有用
        assert any(p in sig.detail for p in ("验证码", "请完成验证", "安全验证", "网络异常", "系统繁忙"))

    @pytest.mark.parametrize("text", [
        "<html><body>正常文章内容</body></html>",
        "搜索结果页",
        "",
    ])
    def test_text_no_match(self, text: str):
        assert detect_risk_by_text(text) is None


class TestHttpLayer:
    @pytest.mark.parametrize("status", [403, 451, 503])
    def test_status_codes(self, status: int):
        resp = MagicMock(status=status, headers={})
        sig = detect_risk_by_http(resp)
        assert sig is not None
        assert sig.layer == "http"
        assert str(status) in sig.detail

    def test_cookie_deleted_header(self):
        resp = MagicMock(status=200, headers={"set-cookie": "BAIDUID_BFESS=deleted; Path=/"})
        sig = detect_risk_by_http(resp)
        assert sig is not None
        assert "BAIDUID_BFESS=deleted" in sig.detail

    def test_normal_response(self):
        resp = MagicMock(status=200, headers={"content-type": "text/html"})
        assert detect_risk_by_http(resp) is None

    def test_response_none(self):
        assert detect_risk_by_http(None) is None


class TestFusion:
    def test_fusion_returns_first_match(self):
        """4 层任一命中即返回该层 RiskSignal。"""
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        page.content.return_value = "<html>正常</html>"
        page.url = "https://wappass.baidu.com/static/captcha/index"
        resp = MagicMock(status=200, headers={})
        sig = detect_risk(page, resp)
        assert sig is not None
        assert sig.layer == "url"

    def test_fusion_no_match_returns_none(self):
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        page.content.return_value = "<html>normal page</html>"
        page.url = "https://www.baidu.com/s?wd=test"
        resp = MagicMock(status=200, headers={})
        assert detect_risk(page, resp) is None

    def test_fusion_http_layer_when_others_miss(self):
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        page.content.return_value = "<html>blocked</html>"
        page.url = "https://www.baidu.com/s?wd=test"
        resp = MagicMock(status=403, headers={})
        sig = detect_risk(page, resp)
        assert sig is not None
        assert sig.layer == "http"
