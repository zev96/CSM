from __future__ import annotations
import pytest

from csm_core.monitor.geo.fail_reason import classify_fail_reason
from csm_core.monitor.geo.models import GeoCell


@pytest.mark.parametrize("status,error,expected", [
    # 未登录:RPA blocked 走 login_blocked_msg(含「未登录」);API 401/unauthorized
    ("blocked", "Kimi 未登录，请在设置中登录", "not_logged_in"),
    ("blocked", "腾讯元宝 未登录，请在设置中扫码登录", "not_logged_in"),
    ("error", "HTTP 401 unauthorized", "not_logged_in"),
    # 限流
    ("error", "HTTP 429 Too Many Requests", "rate_limited"),
    ("error", "触发限流，请稍后重试", "rate_limited"),
    # 配额/欠费
    ("error", "account balance insufficient", "quota_exhausted"),
    ("error", "账户欠费，请充值", "quota_exhausted"),
    # 内容风控
    ("error", "内容触发风控，已拦截", "content_blocked"),
    # 流式超时:wait_stream_done 专属标记,必须早于泛 timeout
    ("error", "TimeoutError: wait_stream_done exceeded 120s", "timeout"),
    # 选择器漂移:Playwright 点击/等待元素超时、找不到元素
    ("error", "Page.click: Timeout 30000ms exceeded. waiting for selector \"button.send\"", "selector_drift"),
    ("error", "locator not found: div.ql-editor", "selector_drift"),
    # 网络/浏览器传输
    ("error", "Target page, context or browser has been closed", "network"),
    ("error", "httpx.ConnectError: connection refused", "network"),
    # 兜底:blocked 但文案未命中 → not_logged_in(最可行动);error → unknown
    ("blocked", "看不懂的中断信息", "not_logged_in"),
    ("error", "看不懂的中断信息", "unknown"),
])
def test_classify_fail_reason(status, error, expected):
    assert classify_fail_reason(status=status, error=error) == expected


def test_stream_timeout_beats_selector_timeout():
    # 两者都含 "timeout";含 wait_stream_done 的必须归 timeout 不是 selector_drift
    assert classify_fail_reason(
        status="error", error="wait_stream_done exceeded 180s (Timeout)") == "timeout"


def test_geocell_has_fail_reason_field_default_empty():
    c = GeoCell(platform="kimi", keyword="k1")
    assert c.fail_reason == ""
    c2 = GeoCell(platform="kimi", keyword="k1", status="error", fail_reason="timeout")
    assert c2.fail_reason == "timeout"
