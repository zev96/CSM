from __future__ import annotations
from csm_core.monitor.platforms import zhihu_content as zc


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload


def test_fetch_text_article_strips_tags(monkeypatch):
    monkeypatch.setattr(zc, "_cc_get", lambda url, **k: _FakeResp(200, {"content": "<p>戴森 V12 实测</p>"}))
    txt = zc.fetch_text("Article", "111", cookie_store=None)
    assert "戴森 V12 实测" in txt
    assert "<p>" not in txt


def test_fetch_text_unsupported_type_returns_none():
    assert zc.fetch_text("Question", "1", cookie_store=None) is None


def test_fetch_text_http_error_returns_none(monkeypatch):
    monkeypatch.setattr(zc, "_cc_get", lambda url, **k: _FakeResp(403, {}))
    assert zc.fetch_text("Answer", "9", cookie_store=None) is None
