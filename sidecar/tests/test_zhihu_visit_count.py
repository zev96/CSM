"""zhihu 问题浏览量抓取测试。"""
from __future__ import annotations
import pytest
from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter


class _FakeResp:
    def __init__(self, status, payload): self.status_code = status; self._p = payload
    def json(self): return self._p


def test_fetch_visit_count_parses_api(monkeypatch):
    """问题详情 API 返回 visit_count → 解析成 int。"""
    def fake_get(url, **kw):
        assert "/api/v4/questions/" in url
        return _FakeResp(200, {"visit_count": 233456, "title": "x"})
    monkeypatch.setattr("curl_cffi.requests.get", fake_get)
    a = ZhihuQuestionAdapter()
    assert a._fetch_visit_count("12345") == 233456


def test_fetch_visit_count_none_on_http_error(monkeypatch):
    monkeypatch.setattr("curl_cffi.requests.get", lambda url, **kw: _FakeResp(403, {}))
    a = ZhihuQuestionAdapter()
    assert a._fetch_visit_count("12345") is None


def test_fetch_includes_visit_count_in_metric(monkeypatch):
    """fetch() 成功路径把 question_visit_count 写进 metric。"""
    from csm_core.monitor.base import MonitorTask
    a = ZhihuQuestionAdapter()
    monkeypatch.setattr(a, "_fetch_fast", lambda qid: (
        [{"author": "u", "content": "戴森好用", "voteup_count": 1, "comment_count": 0, "url": "", "created_time": None}],
        "curl_cffi",
    ))
    monkeypatch.setattr(a, "_fetch_visit_count", lambda qid: 98765)
    task = MonitorTask(
        id=1, type="zhihu_question", name="q",
        target_url="https://www.zhihu.com/question/12345",
        config={"target_brand": "戴森", "top_n": 5},
    )
    result = a.fetch(task)
    assert result.status == "ok"
    assert result.metric["question_visit_count"] == 98765
