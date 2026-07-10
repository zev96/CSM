from __future__ import annotations
import httpx
import pytest

from csm_core.monitor.geo.providers import api_doubao


class _Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text or ""
        self.headers = headers or {}
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
    def post(self, url, **kw):
        self.calls += 1
        return self._responses.pop(0)


def _ok_payload():
    return {"choices": [{"message": {"content": "推荐 CEWEY", "references": []},
                         "finish_reason": "stop"}]}


def test_doubao_retries_once_on_429(monkeypatch):
    fake = _FakeClient([_Resp(429, text="rate", headers={"Retry-After": "0"}),
                        _Resp(200, _ok_payload())])
    monkeypatch.setattr(api_doubao, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_doubao, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_doubao, "get_config",
                        lambda: type("C", (), {"doubao_bot_id": "bot-1", "base_urls": {}})())
    prov = api_doubao.DoubaoProvider()
    ans = prov.query("家用吸尘器哪种好")
    assert ans.status == "ok"
    assert fake.calls == 2                        # 首个 429 → 重试一次 → 200


def test_doubao_no_retry_on_500(monkeypatch):
    fake = _FakeClient([_Resp(500, text="boom")])
    monkeypatch.setattr(api_doubao, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_doubao, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_doubao, "get_config",
                        lambda: type("C", (), {"doubao_bot_id": "bot-1", "base_urls": {}})())
    ans = api_doubao.DoubaoProvider().query("k")
    assert ans.status == "error"                  # 5xx 不属于 429/连接失败 → 不重试
    assert fake.calls == 1
