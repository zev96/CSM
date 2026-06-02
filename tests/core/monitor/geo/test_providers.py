import json
from pathlib import Path
from csm_core.monitor.geo.providers.api_tongyi import parse_tongyi_response
import csm_core.monitor.geo.providers.api_tongyi as tongyi_mod
from csm_core.monitor.geo.providers.api_kimi import parse_kimi_response
import csm_core.monitor.geo.providers.api_kimi as kimi_mod

FIX = Path(__file__).parent / "fixtures"


def test_parse_tongyi_extracts_answer_and_citations():
    raw = json.loads((FIX / "tongyi_search.json").read_text(encoding="utf-8"))
    answer_text, citations = parse_tongyi_response(raw)
    assert "小鹏G6" in answer_text
    urls = [c.url for c in citations]
    assert "https://zhuanlan.zhihu.com/p/123456" in urls
    assert citations[0].title.endswith("知乎")


class _FakeResp:
    def __init__(self, status_code, text, json_data=None, raise_json=False):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self._raise = raise_json

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._json


def test_tongyi_non_json_200_is_error(monkeypatch):
    monkeypatch.setattr(tongyi_mod, "read_api_key", lambda p: "fake-key")
    monkeypatch.setattr(tongyi_mod.httpx, "post",
                        lambda *a, **k: _FakeResp(200, "<html>captcha</html>", raise_json=True))
    ans = tongyi_mod.TongyiProvider().query("k", web_search=True)
    assert ans.status == "error"


def test_tongyi_app_error_code_is_error(monkeypatch):
    monkeypatch.setattr(tongyi_mod, "read_api_key", lambda p: "fake-key")
    monkeypatch.setattr(tongyi_mod.httpx, "post",
                        lambda *a, **k: _FakeResp(200, '{"code":"Arrearage"}',
                                                  json_data={"code": "Arrearage", "message": "欠费"}))
    ans = tongyi_mod.TongyiProvider().query("k", web_search=True)
    assert ans.status == "error"
    assert "Arrearage" in ans.error


def test_tongyi_missing_key_is_error(monkeypatch):
    monkeypatch.setattr(tongyi_mod, "read_api_key", lambda p: "")
    ans = tongyi_mod.TongyiProvider().query("k", web_search=True)
    assert ans.status == "error"


# ── Kimi tests ────────────────────────────────────────────────────────────────

def test_parse_kimi_extracts_answer_and_citations():
    raw = json.loads((FIX / "kimi_search.json").read_text(encoding="utf-8"))
    answer_text, citations = parse_kimi_response(raw)
    assert "小鹏G6" in answer_text
    urls = [c.url for c in citations]
    assert "https://www.zhihu.com/question/600" in urls


def test_kimi_non_json_200_is_error(monkeypatch):
    monkeypatch.setattr(kimi_mod, "read_api_key", lambda p: "fake-key")

    class _FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, *a, **k):
            return _FakeResp(200, "<html>captcha</html>", raise_json=True)

    monkeypatch.setattr(kimi_mod.httpx, "Client", lambda **k: _FakeClient())
    ans = kimi_mod.KimiProvider().query("k", web_search=True)
    assert ans.status == "error"


def test_kimi_missing_key_is_error(monkeypatch):
    monkeypatch.setattr(kimi_mod, "read_api_key", lambda p: "")
    ans = kimi_mod.KimiProvider().query("k", web_search=True)
    assert ans.status == "error"


class _FakeKimiClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        return self._responses.pop(0)


def test_kimi_tool_loop_round_trip(monkeypatch):
    monkeypatch.setattr(kimi_mod, "read_api_key", lambda p: "fake-key")
    round1 = _FakeResp(200, "toolcall", json_data={"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant",
        "tool_calls": [{"id": "tc1", "function": {"name": "$web_search", "arguments": "{\"q\":\"x\"}"}}]}}]})
    round2 = _FakeResp(200, "answer", json_data={"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": "推荐小鹏G6",
        "annotations": [{"type": "url_citation", "url_citation": {"url": "https://www.zhihu.com/q", "title": "知乎"}}]}}]})
    monkeypatch.setattr(kimi_mod.httpx, "Client", lambda *a, **k: _FakeKimiClient([round1, round2]))
    ans = kimi_mod.KimiProvider().query("k", web_search=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
    assert ans.citations[0].url == "https://www.zhihu.com/q"


def test_kimi_content_filter_is_blocked(monkeypatch):
    monkeypatch.setattr(kimi_mod, "read_api_key", lambda p: "fake-key")
    resp = _FakeResp(200, "filtered", json_data={"choices": [{"finish_reason": "content_filter",
                                                              "message": {"role": "assistant", "content": ""}}]})
    monkeypatch.setattr(kimi_mod.httpx, "Client", lambda *a, **k: _FakeKimiClient([resp]))
    ans = kimi_mod.KimiProvider().query("k", web_search=True)
    assert ans.status == "blocked"


# ── Doubao tests ──────────────────────────────────────────────────────────────

from csm_core.monitor.geo.providers.api_doubao import parse_doubao_response
import csm_core.monitor.geo.providers.api_doubao as doubao_mod


def test_parse_doubao_extracts_answer_and_citations():
    raw = json.loads((FIX / "doubao_search.json").read_text(encoding="utf-8"))
    answer_text, citations = parse_doubao_response(raw)
    assert "小鹏G6" in answer_text
    urls = [c.url for c in citations]
    assert "https://zhuanlan.zhihu.com/p/123" in urls
    assert citations[0].title.endswith("知乎")  # site_name 折进 title


def test_doubao_missing_key_is_error(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "")
    ans = doubao_mod.DoubaoProvider(bot_id="bot-x").query("k", web_search=True)
    assert ans.status == "error"


def test_doubao_missing_bot_is_error(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "fake")
    ans = doubao_mod.DoubaoProvider(bot_id="").query("k", web_search=True)
    assert ans.status == "error" and "bot" in ans.error.lower()


def test_doubao_content_filter_is_blocked(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "fake-key")
    monkeypatch.setattr(
        doubao_mod.httpx, "post",
        lambda *a, **k: _FakeResp(
            200, "filtered",
            json_data={"choices": [{"finish_reason": "content_filter",
                                    "message": {"role": "assistant", "content": ""}}]},
        ),
    )
    ans = doubao_mod.DoubaoProvider(bot_id="bot-x").query("k", web_search=True)
    assert ans.status == "blocked"


def test_doubao_sensitive_finish_reason_is_blocked(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "fake-key")
    monkeypatch.setattr(
        doubao_mod.httpx, "post",
        lambda *a, **k: _FakeResp(
            200, "sensitive",
            json_data={"choices": [{"finish_reason": "sensitive",
                                    "message": {"role": "assistant", "content": ""}}]},
        ),
    )
    ans = doubao_mod.DoubaoProvider(bot_id="bot-x").query("k", web_search=True)
    assert ans.status == "blocked"


def test_doubao_http_error_status_is_error(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "fake-key")
    monkeypatch.setattr(
        doubao_mod.httpx, "post",
        lambda *a, **k: _FakeResp(429, "rate limit exceeded"),
    )
    ans = doubao_mod.DoubaoProvider(bot_id="bot-x").query("k", web_search=True)
    assert ans.status == "error"
    assert "429" in ans.error


def test_doubao_app_error_envelope_is_error(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "fake-key")
    monkeypatch.setattr(
        doubao_mod.httpx, "post",
        lambda *a, **k: _FakeResp(
            200, '{"error":{"code":"InvalidApiKey","message":"API key 无效"}}',
            json_data={"error": {"code": "InvalidApiKey", "message": "API key 无效"}},
        ),
    )
    ans = doubao_mod.DoubaoProvider(bot_id="bot-x").query("k", web_search=True)
    assert ans.status == "error"
    assert "API key 无效" in ans.error
