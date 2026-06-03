"""Tests for the zhihu_search monitor adapter (官方搜索 API · 品牌词命中排名)."""
from __future__ import annotations

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms import zhihu_search as zs


def _ok_resp(items, **over):
    d = {"ok": True, "code": 0, "items": items, "empty_reason": None,
         "search_hash_id": "h", "message": "", "http_status": 200, "error": None}
    d.update(over)
    return d


def _err_resp(code, **over):
    d = {"ok": False, "code": code, "items": [], "empty_reason": None,
         "search_hash_id": None, "message": "", "http_status": 200, "error": None}
    d.update(over)
    return d


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


def _task(**cfg):
    return MonitorTask(type="zhihu_search", name="t", target_url="https://z",
                       id=1, config=cfg)


def _patch_secret(monkeypatch, value="secret"):
    monkeypatch.setattr(zs, "read_api_key", lambda provider: value)


def test_fetch_missing_config_fails(monkeypatch):
    _patch_secret(monkeypatch)
    r = zs.ADAPTER.fetch(_task(search_keywords=[], target_brand=""))
    assert r.status == "failed"


def test_fetch_missing_secret_errors(monkeypatch):
    _patch_secret(monkeypatch, value="")
    r = zs.ADAPTER.fetch(_task(search_keywords=["rag"], target_brand="戴森"))
    assert r.status == "error"
    assert "Access Secret" in r.error_message


def test_fetch_ok_aggregates_best_rank(monkeypatch):
    _patch_secret(monkeypatch)

    def fake_api(query, count, secret, **k):
        # kw "a" → 命中在 rank 2；kw "b" → 命中在 rank 1
        if query == "a":
            return _ok_resp([_item(title="无"), _item(title="戴森")])
        return _ok_resp([_item(title="戴森王")])

    monkeypatch.setattr(zs, "zhihu_search_api", fake_api)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a", "b"], target_brand="戴森"))
    assert r.status == "ok"
    assert r.rank == 1  # best across keywords
    assert r.metric["matched_keywords"] == 2
    assert r.metric["total_keywords"] == 2
    assert len(r.metric["keywords"]) == 2


def test_fetch_20001_aborts_with_error(monkeypatch):
    _patch_secret(monkeypatch)
    calls = {"n": 0}

    def fake_api(query, count, secret, **k):
        calls["n"] += 1
        return _err_resp(20001)

    monkeypatch.setattr(zs, "zhihu_search_api", fake_api)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a", "b", "c"], target_brand="戴森"))
    assert r.status == "error"
    assert "20001" in r.error_message
    assert calls["n"] == 1  # 第一次 20001 即中止，不再打后两个关键词


def test_fetch_all_30001_is_risk_control(monkeypatch):
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: _err_resp(30001))
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森"))
    assert r.status == "risk_control"


def _spy_breaker(monkeypatch):
    """Isolate the module-singleton breaker: force allow()=True so a
    previously-opened breaker can't short-circuit fetch(), and replace
    record_success/record_failure with counting spies. Returns the dict.
    """
    calls = {"ok": 0, "fail": 0}
    monkeypatch.setattr(zs.ADAPTER._breaker, "allow", lambda: True)
    monkeypatch.setattr(zs.ADAPTER._breaker, "record_success",
                        lambda: calls.__setitem__("ok", calls["ok"] + 1))
    monkeypatch.setattr(zs.ADAPTER._breaker, "record_failure",
                        lambda: calls.__setitem__("fail", calls["fail"] + 1))
    return calls


def test_fetch_ok_records_breaker_success(monkeypatch):
    """≥1 关键词 code==0 → 一次 record_success，零 record_failure。"""
    _patch_secret(monkeypatch)
    calls = _spy_breaker(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api",
                        lambda *a, **k: _ok_resp([_item(title="戴森")]))
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森"))
    assert r.status == "ok"
    assert calls == {"ok": 1, "fail": 0}


def test_fetch_all_30001_records_breaker_failure(monkeypatch):
    """全 30001 → 一次 record_failure，零 record_success（限流计入熔断器）。"""
    _patch_secret(monkeypatch)
    calls = _spy_breaker(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: _err_resp(30001))
    r = zs.ADAPTER.fetch(_task(search_keywords=["a", "b"], target_brand="戴森"))
    assert r.status == "risk_control"
    assert calls == {"ok": 0, "fail": 1}


def test_fetch_alias_match(monkeypatch):
    """brand_aliases 命中：标题含 'Dyson' 不含 '戴森' → 命中别名。"""
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api",
                        lambda *a, **k: _ok_resp([_item(title="Dyson V15 评测")]))
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森",
                               brand_aliases=["Dyson"]))
    assert r.status == "ok"
    snap = r.metric["keywords"][0]["results"][0]
    assert snap["matches_brand"] is True
    assert snap["matched_brand"] == "Dyson"


def test_fetch_count_clamped_above_max(monkeypatch):
    """count=50 → 传给 API 的 count 被钳到 10（_MAX_COUNT）。"""
    _patch_secret(monkeypatch)
    seen = {}

    def fake_api(query, count, secret, **k):
        seen["count"] = count
        return _ok_resp([])

    monkeypatch.setattr(zs, "zhihu_search_api", fake_api)
    zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", count=50))
    assert seen["count"] == 10


def test_fetch_count_valid_passthrough(monkeypatch):
    """count=5（合法值）→ 原样传给 API。"""
    _patch_secret(monkeypatch)
    seen = {}

    def fake_api(query, count, secret, **k):
        seen["count"] = count
        return _ok_resp([])

    monkeypatch.setattr(zs, "zhihu_search_api", fake_api)
    zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", count=5))
    assert seen["count"] == 5


def test_adapter_registered():
    from csm_core.monitor.platforms import ALL
    assert "zhihu_search" in ALL
    assert ALL["zhihu_search"].platform == "zhihu_search"


def test_fulltext_match_when_excerpt_misses(monkeypatch):
    _patch_secret(monkeypatch)
    # 标题/摘要/作者都不含品牌，但正文含
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0, "items": [_item(title="无关标题", text="无关摘要", author="路人")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    # no_cookie 闸门：必须有 cookie 才会真去回查正文，否则标 no_cookie 不发请求。
    monkeypatch.setattr(zs, "_fulltext_has_cookie", lambda: True)
    monkeypatch.setattr(zs, "_fulltext_fetch", lambda ct, cid: "正文里有 戴森 V12")
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=True))
    res0 = r.metric["keywords"][0]["results"][0]
    assert res0["matches_brand"] is True
    assert res0["matched_field"] == "fulltext"
    assert res0["fulltext_status"] == "matched"


def test_fulltext_disabled_never_fetches(monkeypatch):
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0, "items": [_item(title="无关")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    def boom(ct, cid):
        raise AssertionError("must not fetch when disabled")
    monkeypatch.setattr(zs, "_fulltext_fetch", boom)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=False))
    assert r.metric["keywords"][0]["results"][0]["fulltext_status"] == "disabled"


def test_fulltext_no_cookie(monkeypatch):
    """开关开但知乎 Cookie 池为空 → 每条 no_cookie，绝不发请求（不崩）。"""
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0,
        "items": [_item(title="无关一"), _item(title="无关二")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    monkeypatch.setattr(zs, "_fulltext_has_cookie", lambda: False)
    def boom(ct, cid):
        raise AssertionError("must not fetch when no cookie")
    monkeypatch.setattr(zs, "_fulltext_fetch", boom)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=True))
    results = r.metric["keywords"][0]["results"]
    assert results  # task didn't crash, results present
    assert all(res["fulltext_status"] == "no_cookie" for res in results)
    assert all(res["matches_brand"] is False for res in results)


def test_fulltext_fetch_fail_fallback(monkeypatch):
    """有 cookie 但正文抓取失败（None）→ fetch_failed，回退摘要不崩，excerpt 仍在。"""
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0,
        "items": [_item(title="无关标题", text="某段摘要文本", author="路人")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    monkeypatch.setattr(zs, "_fulltext_has_cookie", lambda: True)
    monkeypatch.setattr(zs, "_fulltext_fetch", lambda ct, cid: None)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=True))
    res0 = r.metric["keywords"][0]["results"][0]
    assert res0["fulltext_status"] == "fetch_failed"
    assert res0["matches_brand"] is False
    assert res0["excerpt"] == "某段摘要文本"  # graceful fallback 仍带摘要


def test_fulltext_fetched_no_match(monkeypatch):
    """有 cookie 且抓到正文但不含品牌 → fetched_no_match，不命中。"""
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0,
        "items": [_item(title="无关标题", text="无关摘要", author="路人")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    monkeypatch.setattr(zs, "_fulltext_has_cookie", lambda: True)
    monkeypatch.setattr(zs, "_fulltext_fetch", lambda ct, cid: "正文里只有别的内容，没有那个品牌")
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=True))
    res0 = r.metric["keywords"][0]["results"][0]
    assert res0["fulltext_status"] == "fetched_no_match"
    assert res0["matches_brand"] is False
