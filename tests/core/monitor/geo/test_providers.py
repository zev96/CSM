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
