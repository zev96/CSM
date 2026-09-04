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
    # HTTP 200 意味着服务端已经出货(可能已计费),所以 from_body 必须为 True,
    # 不应被上层适配器判定为可重试。
    c = _client(lambda req: httpx.Response(200, text="<html>gateway error</html>"))
    with pytest.raises(TikHubError) as e:
        c.get("/p", {})
    assert e.value.from_body is True
    assert e.value.code is None


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


def test_post_sends_json_body_and_auth():
    seen = {}

    def h(req):
        seen["auth"] = req.headers.get("authorization")
        seen["ct"] = req.headers.get("content-type")
        seen["body"] = req.read()
        seen["method"] = req.method
        return httpx.Response(200, json={"code": 200, "data": {"ok": 1}})

    out = _client(h).post("/api/v1/douyin/search/fetch_video_search_v2", {"keyword": "x", "cursor": 0})
    assert out["data"] == {"ok": 1}
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer k"
    assert "application/json" in seen["ct"]
    assert b'"keyword": "x"' in seen["body"] or b'"keyword":"x"' in seen["body"]


def test_post_402_trips_latch():
    c = _client(lambda req: httpx.Response(402, json={"code": 402}))
    with pytest.raises(TikHubBalanceExhausted):
        c.post("/p", {})
    assert balance_exhausted() is True


def test_post_body_code_non_200_raises():
    c = _client(lambda req: httpx.Response(200, json={"code": 500, "message": "boom"}))
    with pytest.raises(TikHubError):
        c.post("/p", {})


def test_get_log_does_not_record_param_values(caplog):
    # GET 参数可能带 keyword 等业务敏感值(如 Bilibili/Kuaishou 搜索的 keyword)——
    # 日志只能记参数名列表,不能记值。
    with caplog.at_level(logging.INFO, logger="csm_core.monitor.tikhub.client"):
        _client(lambda req: httpx.Response(200, json={"code": 200, "data": {}})).get(
            "/p", {"keyword": "秘密词", "page": 1}
        )
    assert "秘密词" not in caplog.text
    assert "keyword" in caplog.text


def test_from_body_true_when_http_200_body_code_error():
    # HTTP 200 + body code != 200:服务端已经出货(可能已计费),from_body 必须为 True。
    c = _client(lambda req: httpx.Response(200, json={"code": 500, "message": "boom"}))
    with pytest.raises(TikHubError) as ei:
        c.get("/p", {})
    assert ei.value.from_body is True
    assert ei.value.code == 500


def test_from_body_false_when_http_status_error():
    c = _client(lambda req: httpx.Response(500, json={"code": 500}))
    with pytest.raises(TikHubError) as ei:
        c.get("/p", {})
    assert ei.value.from_body is False
    assert ei.value.code == 500


def test_from_body_false_on_network_error():
    def h(req):
        raise httpx.ConnectError("x")

    c = _client(h)
    with pytest.raises(TikHubError) as ei:
        c.get("/p", {})
    assert ei.value.from_body is False
    assert ei.value.code is None


def test_string_body_code_402_trips_latch_and_from_body_true():
    # 聚合 API 有时把 code 编码成字符串而不是 int —— "402" 也必须识别为业务错误。
    c = _client(lambda req: httpx.Response(200, json={"code": "402", "message": "no balance"}))
    with pytest.raises(TikHubBalanceExhausted) as ei:
        c.get("/p", {})
    assert balance_exhausted() is True
    assert ei.value.from_body is True


def test_string_body_code_200_returns_data():
    c = _client(lambda req: httpx.Response(200, json={"code": "200", "data": {}}))
    assert c.get("/p", {}) == {"code": "200", "data": {}}


def test_bool_body_code_does_not_raise():
    # bool 是 int 子类(True == 1) —— 不能被误判成业务码 1(!= 200)而错误报错。
    c = _client(lambda req: httpx.Response(200, json={"code": True, "data": {"x": 1}}))
    assert c.get("/p", {})["data"] == {"x": 1}


def test_superscript_digit_body_code_does_not_raise_as_python_error():
    # '²'.isdigit() 是 True 但 int('²') 抛 ValueError —— isdigit() 误判成"这是数字
    # 字符串"会让 int() 转换炸出 ValueError,以非 TikHubError 形态击穿上层。必须用
    # isdecimal() 才能正确识别"这不是可转 int 的十进制数字"从而保留原样透传。
    c = _client(lambda req: httpx.Response(200, json={"code": "²", "data": {"x": 1}}))
    assert c.get("/p", {})["data"] == {"x": 1}


def test_fullwidth_digit_body_code_still_trips_balance_latch():
    # 全角数字(如 "４０２")isdigit()/isdecimal() 都认,且 int() 能正确转换 ——
    # 确认改用 isdecimal() 不会漏识别这类合法但非 ASCII 的数字业务码。
    c = _client(lambda req: httpx.Response(200, json={"code": "４０２", "message": "no balance"}))
    with pytest.raises(TikHubBalanceExhausted):
        c.get("/p", {})
    assert balance_exhausted() is True
