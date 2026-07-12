from __future__ import annotations
import httpx
import pytest

from csm_core.monitor.geo.providers import api_tongyi


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
    return {"output": {"choices": [{"message": {"content": "推荐 CEWEY"},
                                    "finish_reason": "stop"}],
                       "search_info": {"search_results": []}}}


def test_tongyi_retries_once_on_429(monkeypatch):
    fake = _FakeClient([_Resp(429, text="rate", headers={"Retry-After": "0"}),
                        _Resp(200, _ok_payload())])
    monkeypatch.setattr(api_tongyi, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_tongyi, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_tongyi, "get_config",
                        lambda: type("C", (), {"default_model": {}})())
    ans = api_tongyi.TongyiProvider().query("家用吸尘器哪种好")
    assert ans.status == "ok"
    assert fake.calls == 2


def test_tongyi_no_retry_on_500(monkeypatch):
    fake = _FakeClient([_Resp(500, text="boom")])
    monkeypatch.setattr(api_tongyi, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_tongyi, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_tongyi, "get_config",
                        lambda: type("C", (), {"default_model": {}})())
    ans = api_tongyi.TongyiProvider().query("k")
    assert ans.status == "error"
    assert fake.calls == 1
