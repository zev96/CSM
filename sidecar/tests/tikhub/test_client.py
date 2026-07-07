import logging

import pytest, httpx
from csm_core.monitor.tikhub.client import (
    TikHubClient,
    balance_exhausted,
    reset_balance_latch,
)
from csm_core.monitor.tikhub.errors import TikHubError, TikHubBalanceExhausted


@pytest.fixture(autouse=True)
def _reset_latch():
    # 402 余额闩是进程级全局状态 —— 每个用例前后重置,避免测试互相污染。
    reset_balance_latch()
    yield
    reset_balance_latch()


def _client(handler, api_key="k"):
    transport = httpx.MockTransport(handler)
    return TikHubClient(base_url="https://api.tikhub.dev", api_key=api_key, _transport=transport)


def test_get_ok_returns_data():
    c = _client(lambda req: httpx.Response(200, json={"code": 200, "data": {"x": 1}}))
    assert c.get("/p", {}) == {"code": 200, "data": {"x": 1}}


def test_402_raises_balance_exhausted():
    c = _client(lambda req: httpx.Response(402, json={"code": 402, "message": "no balance"}))
    with pytest.raises(TikHubBalanceExhausted):
        c.get("/p", {})
    assert balance_exhausted() is True


def test_429_maps_to_chinese_reason():
    c = _client(lambda req: httpx.Response(429, json={"code": 429}))
    with pytest.raises(TikHubError) as e:
        c.get("/p", {})
    assert "限流" in str(e.value.reason)


def test_auth_header_present():
    seen = {}

    def h(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"code": 200, "data": {}})

    _client(h).get("/p", {})
    assert seen["auth"] == "Bearer k"


def test_http_200_but_body_code_402_trips_latch():
    # 聚合 API 常用 HTTP 200 + body code 表业务错误 —— 必须也能识别并置闩。
    c = _client(lambda req: httpx.Response(200, json={"code": 402, "message": "no balance"}))
    with pytest.raises(TikHubBalanceExhausted):
        c.get("/p", {})
    assert balance_exhausted() is True


def test_body_code_200_returns_full_wrapper():
    c = _client(lambda req: httpx.Response(200, json={"code": 200, "data": {"ok": 1}}))
    assert c.get("/p", {})["data"] == {"ok": 1}


def test_non_json_response_raises_tikhub_error():
    # 网关错误页 / 截断响应 -> 统一成 TikHubError,不让 JSONDecodeError 击穿上层。
    c = _client(lambda req: httpx.Response(200, text="<html>gateway error</html>"))
    with pytest.raises(TikHubError):
        c.get("/p", {})


def test_log_redacts_key_from_echoed_error_body(caplog):
    # 网关把请求头回显进错误体时,日志绝不能出现 key(R7 安全红线)。
    secret = "sk-th-SUPERSECRET-abc123"

    def h(req):
        return httpx.Response(500, text='{"authorization":"Bearer ' + secret + '"}')

    c = _client(h, api_key=secret)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(TikHubError):
            c.get("/p", {})
    assert secret not in caplog.text
    assert "***" in caplog.text
