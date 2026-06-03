"""Tests for the zhihu_search monitor adapter (官方搜索 API · 品牌词命中排名)."""
from __future__ import annotations

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms import zhihu_search as zs


def test_zhihu_search_is_valid_task_type():
    """MonitorTask 接受 type='zhihu_search'（Literal 已扩展）。"""
    t = MonitorTask(type="zhihu_search", name="测试", target_url="https://x")
    assert t.type == "zhihu_search"


class _FakeResp:
    def __init__(self, status_code: int, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


_OK_PAYLOAD = {
    "Code": 0,
    "Message": "success",
    "Data": {
        "HasMore": False,
        "SearchHashId": "hash123",
        "Items": [
            {
                "Title": "RAG 评测方法综述",
                "ContentType": "Article",
                "ContentID": "111",
                "ContentText": "本文介绍主流 RAG 评测框架…",
                "Url": "https://zhuanlan.zhihu.com/p/111?utm_x=1",
                "CommentCount": 15,
                "VoteUpCount": 128,
                "AuthorName": "张三",
                "AuthorityLevel": "2",
                "EditTime": 1710000000,
                "RankingScore": 0.98,
            }
        ],
    },
}


def test_api_ok_parses_items(monkeypatch):
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, _OK_PAYLOAD))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is True
    assert out["code"] == 0
    assert out["search_hash_id"] == "hash123"
    assert len(out["items"]) == 1
    assert out["items"][0]["Title"] == "RAG 评测方法综述"


def test_api_30001_marked_not_ok(monkeypatch):
    payload = {"Code": 30001, "Message": "rate limited", "Data": {}}
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, payload))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert out["code"] == 30001
    assert out["items"] == []


def test_api_empty_reason_passthrough(monkeypatch):
    payload = {"Code": 0, "Message": "ok", "Data": {"Items": [], "EmptyReason": "无结果"}}
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, payload))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is True
    assert out["empty_reason"] == "无结果"
    assert out["items"] == []


def test_api_http_500_is_error(monkeypatch):
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(500, None))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert out["http_status"] == 500
    assert out["error"]


def test_api_non_json_is_error(monkeypatch):
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, None, raise_json=True))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert "non-JSON" in out["error"]


def test_api_transport_exception_is_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("conn reset")
    monkeypatch.setattr(zs.httpx, "get", boom)
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert "conn reset" in out["error"]
