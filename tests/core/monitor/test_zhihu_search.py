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


def _item(title="", text="", author=""):
    return {"Title": title, "ContentText": text, "AuthorName": author,
            "ContentType": "Article", "ContentID": "x", "Url": "https://z/x",
            "VoteUpCount": 0, "CommentCount": 0, "AuthorityLevel": "0",
            "EditTime": 0, "RankingScore": 0.0}


def test_match_brand_case_insensitive_and_order():
    assert zs.match_brand("I love Claude Code", ["claude"]) == "claude"
    assert zs.match_brand("无关", ["claude"]) is None
    # 顺序代表优先级：主品牌排前
    assert zs.match_brand("anthropic claude", ["claude", "anthropic"]) == "claude"


def test_match_item_field_precedence():
    # 标题命中优先
    assert zs.ZhihuSearchAdapter._match_item(_item(title="戴森评测"), ["戴森"]) == ("戴森", "title")
    # 标题没有 → 摘要
    assert zs.ZhihuSearchAdapter._match_item(_item(text="我用戴森"), ["戴森"]) == ("戴森", "excerpt")
    # 都没有 → 作者
    assert zs.ZhihuSearchAdapter._match_item(_item(author="戴森官方"), ["戴森"]) == ("戴森", "author")
    # 全无 → (None, None)
    assert zs.ZhihuSearchAdapter._match_item(_item(title="小米"), ["戴森"]) == (None, None)


def test_rank_results_first_rank_and_count():
    items = [
        _item(title="小米吸尘器"),       # 1
        _item(text="戴森 V12 真香"),      # 2 ✓
        _item(author="添可"),            # 3
        _item(title="戴森对比小米"),      # 4 ✓
    ]
    first, count, snap = zs.ZhihuSearchAdapter._rank_results(items, ["戴森"], 10)
    assert first == 2
    assert count == 2
    assert len(snap) == 4
    assert snap[1]["matches_brand"] is True
    assert snap[1]["matched_field"] == "excerpt"
    assert snap[0]["matches_brand"] is False
    # 摘要截断 160
    assert len(snap[0]["excerpt"]) <= 160


def test_rank_results_no_match_returns_minus_one():
    items = [_item(title="小米"), _item(title="添可")]
    first, count, snap = zs.ZhihuSearchAdapter._rank_results(items, ["戴森"], 10)
    assert first == -1
    assert count == 0
    assert len(snap) == 2


def test_rank_results_respects_count_cap():
    items = [_item(title="无关")] * 9 + [_item(title="戴森")]  # 命中在第 10
    first, count, snap = zs.ZhihuSearchAdapter._rank_results(items, ["戴森"], 5)
    assert first == -1  # 只看前 5
    assert len(snap) == 5
