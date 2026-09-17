"""小红书（TikHub 路径）—— 评论留存 + 采集搜索：归一化 / 翻页 / 分派 / 链接解析 / 预筛路由。

字段路径尚未用真实 token 实测（抖音 / B站 / 快手三家 2026-09-01 实测过）；这里用合成响应
钉死结构性约定：信封两层拆包、cursor+index+pageArea 三元组翻页、平台级错误绝不当"空评论区"、
链接各种形态解析、local 模式下的占位适配器不发请求。真 fixture 落地后
（``tikhub_probe.py --xhs / --xhs-search``）末尾的 real-fixture 用例会自动生效。
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from csm_core.mining import runner
from csm_core.mining.models import SearchFilters, StartJobRequest
from csm_core.mining.platforms import tikhub_normalize as N
from csm_core.mining.platforms.tikhub_search import TikHubSearchAdapter
from csm_core.mining.storage import _PLATFORM_TO_MONITOR_TYPE, extract_platform_video_id
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.platforms.xiaohongshu_comment import (
    ADAPTER as XHS_LOCAL, NO_LOCAL_PATH_MESSAGE, XiaohongshuCommentAdapter,
)
from csm_core.monitor.tikhub import build_api_adapters
from csm_core.monitor.tikhub.comment_adapter import (
    XHS_SORT_STRATEGY, XIAOHONGSHU_SPEC, CommentApiAdapter,
)
from csm_core.monitor.tikhub.errors import TikHubError
from csm_core.monitor.tikhub.normalize import (
    normalize_xiaohongshu_comments, xiaohongshu_comment_page,
)

FIX = pathlib.Path(__file__).parent / "fixtures"
NOTE = "64f1c2a3000000001e03ab12"
DEPTH = XIAOHONGSHU_SPEC.depth_cap


def _envelope(inner: dict, *, code=0, success=True, msg="成功") -> dict:
    """TikHub 外层 + 小红书信封 + 真数据层。"""
    return {"code": 200, "data": {"code": code, "success": success, "msg": msg, "data": inner}}


def _comment(text, author="u", likes=0):
    return {"content": text, "user": {"nickname": author}, "like_count": likes}


# ── 评论归一化 ──────────────────────────────────────────────────────────

def test_normalize_comments_nested_envelope():
    raw = _envelope({
        "comments": [_comment("一楼", "甲", "1.2万"), _comment("二楼", "乙", 3), "not-a-dict"],
        "cursor": "c2", "index": 2, "pageArea": "UNFOLDED", "has_more": True,
    })
    out = normalize_xiaohongshu_comments(raw)
    assert out == [
        {"rank": 1, "text": "一楼", "author": "甲", "likes": 12000},
        {"rank": 2, "text": "二楼", "author": "乙", "likes": 3},
    ]
    assert xiaohongshu_comment_page(raw)["cursor"] == "c2"


def test_normalize_comments_flat_data_layer():
    """服务端把信封摊平（data 直接带 comments）也认。"""
    raw = {"code": 200, "data": {"comments": [_comment("x")], "cursor": ""}}
    assert [c["text"] for c in normalize_xiaohongshu_comments(raw)] == ["x"]
    assert xiaohongshu_comment_page(raw) is raw["data"]


def test_normalize_comments_garbage_is_empty():
    assert normalize_xiaohongshu_comments({}) == []
    assert normalize_xiaohongshu_comments({"data": "x"}) == []
    assert normalize_xiaohongshu_comments({"data": {"data": {"comments": "nope"}}}) == []


# ── parse_page / build_params：三元组游标 + 平台级错误 ──────────────────────

def test_parse_page_platform_error_raises_not_empty():
    """笔记不存在 / 限流：TikHub 照常计费且 HTTP 200，绝不能当空评论区。"""
    with pytest.raises(TikHubError, match="笔记不存在"):
        XIAOHONGSHU_SPEC.parse_page({"data": {"code": -1, "success": False, "msg": "笔记不存在"}}, True)
    with pytest.raises(TikHubError):
        XIAOHONGSHU_SPEC.parse_page({"data": {"code": 300, "data": {"comments": []}}}, True)


def test_parse_page_cursor_triplet_and_has_more():
    items, nxt, more = XIAOHONGSHU_SPEC.parse_page(_envelope({
        "comments": [_comment("a")], "cursor": "c2", "index": 10, "pageArea": "UNFOLDED", "has_more": True,
    }), True)
    assert [i["text"] for i in items] == ["a"]
    assert nxt == {"cursor": "c2", "index": 10, "pageArea": "UNFOLDED"}
    assert more is True
    assert XIAOHONGSHU_SPEC.build_params(NOTE, "", None) == {"note_id": NOTE, "sort_strategy": XHS_SORT_STRATEGY}
    assert XIAOHONGSHU_SPEC.build_params(NOTE, "", nxt) == {
        "note_id": NOTE, "sort_strategy": XHS_SORT_STRATEGY,
        "cursor": "c2", "index": 10, "pageArea": "UNFOLDED",
    }
    # has_more 显式为假 → 停
    _, nxt2, more2 = XIAOHONGSHU_SPEC.parse_page(_envelope({"comments": [], "cursor": "c3", "has_more": 0}), False)
    assert nxt2 is not None and more2 is False
    # has_more 缺失 → 有 cursor 就当还有
    _, nxt3, more3 = XIAOHONGSHU_SPEC.parse_page(_envelope({"comments": [_comment("b")], "cursor": "c4"}), False)
    assert nxt3["cursor"] == "c4" and more3 is True
    # cursor 缺失 → 没有下一页
    _, nxt4, more4 = XIAOHONGSHU_SPEC.parse_page(_envelope({"comments": [_comment("c")], "has_more": True}), False)
    assert nxt4 is None and more4 is False


# ── CommentApiAdapter × 小红书 spec ────────────────────────────────────────

def _xtask(text="MINE", top_n=5):
    return MonitorTask(type="xiaohongshu_comment", name="t",
                       target_url=f"https://www.xiaohongshu.com/explore/{NOTE}",
                       config={"my_comment_text": text, "top_n": top_n})


def test_adapter_finds_comment_on_second_page_passing_triplet():
    calls = []

    def page(endpoint, params):
        calls.append((endpoint, dict(params)))
        if "cursor" not in params:
            return _envelope({"comments": [_comment(f"c{i}") for i in range(1, 11)],
                              "cursor": "p2", "index": 10, "pageArea": "UNFOLDED", "has_more": True})
        comments = [_comment("MINE" if i == 3 else f"d{i}") for i in range(1, 11)]
        return _envelope({"comments": comments, "cursor": "p3", "index": 20, "pageArea": "UNFOLDED", "has_more": True})

    client = MagicMock(); client.get.side_effect = page
    a = CommentApiAdapter(XIAOHONGSHU_SPEC, client_factory=lambda: client, id_extractor=lambda url: (NOTE, ""))
    r = a.fetch(_xtask())
    assert r.status == "ok" and r.metric["matched"] is True
    assert r.rank == 13                                   # 跨页全局重排：第 2 页第 3 条
    assert len(calls) == 2                                # 命中即停
    assert calls[0][0] == "/api/v1/xiaohongshu/app_v2/get_note_comments"
    assert calls[0][1] == {"note_id": NOTE, "sort_strategy": "like_count"}
    assert calls[1][1] == {"note_id": NOTE, "sort_strategy": "like_count",
                           "cursor": "p2", "index": 10, "pageArea": "UNFOLDED"}
    assert r.metric["source"] == "tikhub" and r.metric["depth_cap"] == DEPTH


def test_adapter_platform_error_is_failed_not_deleted():
    client = MagicMock()
    client.get.return_value = {"data": {"code": -1, "success": False, "msg": "笔记不存在"}}
    a = CommentApiAdapter(XIAOHONGSHU_SPEC, client_factory=lambda: client, id_extractor=lambda url: (NOTE, ""))
    r = a.fetch(_xtask())
    assert r.status == "failed" and "小红书接口错误" in r.error_message


def test_adapter_bad_url_fails_before_spending():
    client = MagicMock()
    a = CommentApiAdapter(XIAOHONGSHU_SPEC, client_factory=lambda: client, id_extractor=lambda url: (None, ""))
    assert a.fetch(_xtask()).status == "failed"
    client.get.assert_not_called()


def test_build_api_adapters_includes_xiaohongshu():
    ad = build_api_adapters(lambda: MagicMock(), lambda p, c=None: "k")
    a = ad["xiaohongshu_comment"]
    assert isinstance(a, CommentApiAdapter) and a.platform == "xiaohongshu_comment"


# ── 链接 → 笔记 ID ─────────────────────────────────────────────────────

def test_extract_note_id_long_links_and_bare_id():
    ex = XiaohongshuCommentAdapter._extract_note_id
    assert ex(None, f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token=AB=&xsec_source=pc_search") == (NOTE, "")
    assert ex(None, f"https://www.xiaohongshu.com/discovery/item/{NOTE}?source=webshare") == (NOTE, "")
    assert ex(None, NOTE.upper()) == (NOTE, "")
    assert ex(None, "https://www.xiaohongshu.com/user/profile/abc")[0] is None
    assert ex(None, "")[0] is None


def test_extract_note_id_from_share_text_expands_short_link():
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        url=f"https://www.xiaohongshu.com/discovery/item/{NOTE}?xsec_token=x", status_code=200,
    )
    text = f"72 【好物 - 某某 | 小红书 - 你的生活兴趣社区】 😆 abc 😆 http://xhslink.com/a/AbCdEf，复制本条信息，打开【小红书】App查看精彩内容！"
    assert XiaohongshuCommentAdapter._extract_note_id(session, text) == (NOTE, "")
    called_url = session.get.call_args[0][0]
    assert called_url == "http://xhslink.com/a/AbCdEf"        # 中文标点截断，不把「，复制」带进 URL


def test_extract_note_id_short_link_failure_is_none():
    session = MagicMock(); session.get.side_effect = RuntimeError("boom")
    assert XiaohongshuCommentAdapter._extract_note_id(session, "http://xhslink.cn/z/1")[0] is None


def test_local_placeholder_fails_with_guidance():
    r = XHS_LOCAL.fetch(_xtask())
    assert r.status == "failed" and r.error_message == NO_LOCAL_PATH_MESSAGE and "TikHub" in r.error_message


# ── 采集搜索：参数 / 翻页 / 归一化 ──────────────────────────────────────

def test_search_first_params_maps_ui_filters_to_api_values():
    assert N.xiaohongshu_first_params("宠物吸尘器", {
        "sort_type": "popularity_descending", "note_type": "video", "time_filter": "7",
    }) == {"keyword": "宠物吸尘器", "page": 1, "sort_type": "popularity_descending",
           "note_type": "视频笔记", "time_filter": "一周内"}
    assert N.xiaohongshu_first_params("k", {"sort_type": "junk", "note_type": 9, "time_filter": "x"}) == {
        "keyword": "k", "page": 1, "sort_type": "general", "note_type": "不限", "time_filter": "不限",
    }
    assert N.xiaohongshu_first_params("k", None)["note_type"] == "不限"


def _search_raw(items, **page_extra):
    return {"code": 200, "data": {"code": 0, "success": True, "data": {"items": items, **page_extra}}}


def _note_item(nid, **note):
    base = {"id": nid, "title": f"标题{nid[-2:]}", "desc": "正文\n第二行", "type": "video",
            "user": {"nickname": "博主", "userid": "u1"},
            "images_list": [{"url": "https://img/1.jpg", "width": 1}],
            "liked_count": "1.2万", "time": 1735635697,
            "video_info": {"duration": 95}}
    base.update(note)
    return {"model_type": "note", "note": base, "xsec_token": "TOK="}


def test_search_next_params_carries_search_ids_and_stops():
    prev = N.xiaohongshu_first_params("k", {})
    nxt = N.xiaohongshu_next_params(prev, _search_raw([_note_item(NOTE)], search_id="S1", search_session_id="SS1"))
    assert nxt["page"] == 2 and nxt["search_id"] == "S1" and nxt["search_session_id"] == "SS1"
    # 后续页没回 id → 沿用上一页的
    nxt2 = N.xiaohongshu_next_params(nxt, _search_raw([_note_item(NOTE)]))
    assert nxt2["page"] == 3 and nxt2["search_id"] == "S1"
    assert N.xiaohongshu_next_params(prev, _search_raw([_note_item(NOTE)], has_more=False)) is None
    assert N.xiaohongshu_next_params(prev, _search_raw([])) is None
    assert N.xiaohongshu_next_params(prev, {"data": "garbage"}) is None


def test_search_normalize_nested_and_flat_items():
    other = "64f1c2a3000000001e03ab34"
    raw = _search_raw([
        _note_item(NOTE),
        {"model_type": "user", "user": {"nickname": "x"}},                 # 非笔记卡 → 跳过
        {"model_type": "note", "note": {"title": "无 id"}},                 # 缺 id → 跳过
        {"note_id": other, "display_title": "摊平笔记", "type": "normal",  # 形态 B：字段摊平
         "user": {"user_id": "u2", "name": "路人"}, "cover": {"url": "https://img/c.jpg"},
         "interact_info": {"liked_count": 7}, "timestamp": 1735635697000},
    ], search_id="S1")
    cards = N.normalize_xiaohongshu_search(raw, {})
    assert [c.platform_video_id for c in cards] == [NOTE, other]
    a, b = cards
    assert a.platform == "xiaohongshu"
    assert a.url == f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token=TOK=&xsec_source=pc_search"
    assert a.title.startswith("标题") and a.author_name == "博主" and a.author_id == "u1"
    assert a.cover_url == "https://img/1.jpg" and a.duration_sec == 95
    assert a.like_count == 12000 and a.play_count is None
    assert a.published_at == "2024-12-31T09:01:37Z"
    assert "images_list" not in a.raw and "video_info" not in a.raw and "_xsec_token" not in a.raw
    assert b.url == f"https://www.xiaohongshu.com/explore/{other}"          # 无 xsec_token → 裸链
    assert b.title == "摊平笔记" and b.author_name == "路人" and b.author_id == "u2"
    assert b.cover_url == "https://img/c.jpg" and b.like_count == 7 and b.duration_sec is None
    assert b.published_at == "2024-12-31T09:01:37Z"                          # 毫秒时间戳折算


def test_search_normalize_title_falls_back_to_desc_and_ms_duration():
    raw = _search_raw([_note_item(NOTE, title="", desc="  首行当标题\n次行", video_info={"duration": 95000})])
    (card,) = N.normalize_xiaohongshu_search(raw, {})
    assert card.title == "首行当标题" and card.duration_sec == 95


def test_search_normalize_flat_data_layer_and_garbage():
    raw = {"code": 200, "data": {"items": [_note_item(NOTE)]}}
    assert len(N.normalize_xiaohongshu_search(raw, {})) == 1
    assert N.normalize_xiaohongshu_search({"data": "x"}, {}) == []
    assert N.normalize_xiaohongshu_search({}, {}) == []


def test_search_dispatch_tikhub_vs_local():
    a = runner.get_adapter("xiaohongshu", "tikhub_api")
    assert isinstance(a, TikHubSearchAdapter) and a.platform == "xiaohongshu"
    assert a.spec.path == "/api/v1/xiaohongshu/app_v2/search_notes" and a.spec.method == "GET"

    local = runner.get_adapter("xiaohongshu", "local")
    assert isinstance(local, runner.UnsupportedLocalSearchAdapter)
    progress = []
    outcome = local.search("k", 50, on_card=lambda c: pytest.fail("must not emit"),
                           on_progress=progress.append, cancel_event=MagicMock())
    assert outcome.status == "failed" and outcome.cards_emitted == 0 and "TikHub" in outcome.error_message
    assert progress and progress[0].phase == "failed" and progress[0].target == 50
    with pytest.raises(ValueError):
        runner.get_adapter("xhs", "local")


def test_start_job_request_accepts_xiaohongshu_and_four_platforms():
    req = StartJobRequest(keyword="k", platforms=["douyin", "bilibili", "kuaishou", "xiaohongshu", "xiaohongshu"])
    assert req.platforms == ["douyin", "bilibili", "kuaishou", "xiaohongshu"]
    f = SearchFilters().model_dump()
    assert f["xiaohongshu"] == {"sort_type": "general", "note_type": "all", "time_filter": "0"}


def test_storage_note_id_patterns_and_monitor_type():
    assert extract_platform_video_id("xiaohongshu", f"https://www.xiaohongshu.com/explore/{NOTE}?xsec_token=a") == NOTE
    assert extract_platform_video_id("xiaohongshu", f"https://www.xiaohongshu.com/discovery/item/{NOTE}") == NOTE
    assert extract_platform_video_id("xiaohongshu", "https://www.xiaohongshu.com/user/profile/x") is None
    assert _PLATFORM_TO_MONITOR_TYPE["xiaohongshu"] == "xiaohongshu_comment"


# ── 预筛路由：小红书只走 TikHub，缺 key 跳过（fail-open）─────────────────────

def _ok_result(texts):
    return MonitorResult(task_id=0, checked_at=datetime(2026, 1, 1), status="ok", rank=1,
                         metric={"hot_comments": [{"text": t, "likes": 1, "author": "a"} for t in texts]})


def test_prefilter_xiaohongshu_routes_to_tikhub_with_key(monkeypatch):
    from csm_core.mining import comment_prefilter as mod
    monkeypatch.setattr("csm_core.config.read_api_key", lambda *a, **k: "sk-test")
    api = MagicMock(); api.fetch.return_value = _ok_result(["via tikhub"])
    monkeypatch.setattr("csm_core.monitor.tikhub.build_api_adapters", lambda g, k: {"xiaohongshu_comment": api})
    local = MagicMock()
    with patch.dict("csm_core.monitor.platforms.ALL", {"xiaohongshu_comment": local}, clear=False):
        out = mod.fetch_video_comments("xiaohongshu", f"https://www.xiaohongshu.com/explore/{NOTE}", limit=20)
    assert [c["text"] for c in out] == ["via tikhub"]
    assert api.fetch.call_args[0][0].type == "xiaohongshu_comment"
    local.fetch.assert_not_called()


def test_prefilter_xiaohongshu_without_key_skips_not_local(monkeypatch):
    from csm_core.mining import comment_prefilter as mod
    monkeypatch.setattr("csm_core.config.read_api_key", lambda *a, **k: "")
    local = MagicMock(); local.fetch.return_value = _ok_result(["should not be used"])
    with patch.dict("csm_core.monitor.platforms.ALL", {"xiaohongshu_comment": local}, clear=False):
        assert mod.fetch_video_comments("xiaohongshu", f"https://www.xiaohongshu.com/explore/{NOTE}") == []
    local.fetch.assert_not_called()


# ── 各处平台枚举都带上小红书 ─────────────────────────────────────────────

def test_platform_enums_include_xiaohongshu():
    from csm_core.monitor.platforms import ALL
    from csm_sidecar.services import history_service, monitor_service
    assert "xiaohongshu_comment" in monitor_service.PLATFORM_TYPES
    assert "xiaohongshu_comment" in history_service.COMMENT_PLATFORMS
    assert history_service.PLATFORM_LABELS["xiaohongshu_comment"] == "小红书"
    assert ALL["xiaohongshu_comment"] is XHS_LOCAL


# ── 真 fixture（用 tikhub_probe.py --xhs / --xhs-search 抓到后自动生效）────

@pytest.mark.skipif(not (FIX / "tikhub_xiaohongshu_comments.json").exists(), reason="no real fixture yet")
def test_real_comments_fixture():
    raw = json.loads((FIX / "tikhub_xiaohongshu_comments.json").read_text(encoding="utf-8"))
    out = normalize_xiaohongshu_comments(raw)
    assert out and all(o["text"] for o in out)
    assert all(set(o) == {"rank", "text", "author", "likes"} for o in out)
    assert all(o["rank"] == i + 1 for i, o in enumerate(out))


@pytest.mark.skipif(not (FIX / "tikhub_search_xiaohongshu.json").exists(), reason="no real fixture yet")
def test_real_search_fixture():
    raw = json.loads((FIX / "tikhub_search_xiaohongshu.json").read_text(encoding="utf-8"))
    cards = N.normalize_xiaohongshu_search(raw, {})
    assert cards and all(N._XHS_NOTE_ID_RE.match(c.platform_video_id) for c in cards)
    assert all(c.url.startswith("https://www.xiaohongshu.com/explore/") for c in cards)
