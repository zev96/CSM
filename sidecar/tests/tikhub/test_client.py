import pytest, httpx
from csm_core.monitor.tikhub.client import TikHubClient
from csm_core.monitor.tikhub.errors import TikHubError, TikHubBalanceExhausted


def _client(handler):
    transport = httpx.MockTransport(handler)
    return TikHubClient(base_url="https://api.tikhub.dev", api_key="k", _transport=transport)


def test_get_ok_returns_data():
    c = _client(lambda req: httpx.Response(200, json={"code": 200, "data": {"x": 1}}))
    assert c.get("/p", {}) == {"code": 200, "data": {"x": 1}}


def test_402_raises_balance_exhausted():
    c = _client(lambda req: httpx.Response(402, json={"code": 402, "message": "no balance"}))
    with pytest.raises(TikHubBalanceExhausted):
        c.get("/p", {})


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
