"""B 站「UP 主精选评论」识别：评论接口 data 层 → featured_only → metric。

开启后评论框提示「评论被up主精选后，对所有人可见」—— 访客评论要被 UP 主手动
精选才公开。mining 引流预筛读 metric.featured_only 跳过这类视频。
响应形状取自 2026-09 对 x/v2/reply/main 的实测。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms._comment_shared import CommentSnapshot, result_from_snapshot
from csm_core.monitor.platforms.bilibili_comment import (
    BilibiliCommentAdapter, featured_only_from_reply_data,
)

FEATURED = {
    "cursor": {"is_begin": True, "is_end": True, "mode": 3, "support_mode": [3], "name": "精选评论"},
    "replies": [],
    "control": {
        "root_input_text": "评论被up主精选后，对所有人可见",
        "child_input_text": "评论被up主精选后，对所有人可见",
        "show_type": 2,
        "web_selection": True,
    },
}
NORMAL = {
    "cursor": {"is_begin": True, "is_end": True, "mode": 3, "support_mode": [2, 3], "name": "热门评论"},
    "replies": [{"content": {"message": "路过"}, "member": {"uname": "u"}, "like": 3}],
    "control": {
        "root_input_text": "勇敢滴少年啊快去创造热评~",
        "show_type": 1,
        "web_selection": False,
    },
}


def test_detects_featured_and_normal():
    assert featured_only_from_reply_data(FEATURED) is True
    assert featured_only_from_reply_data(NORMAL) is False


def test_text_fallbacks_survive_field_rename():
    """web_selection 哪天改名 / 消失：评论框文案、列表标题任一仍能认出来。"""
    by_hint = {"control": {"root_input_text": "评论被up主精选后，对所有人可见"}}
    by_title = {"cursor": {"name": "精选评论"}, "control": {}}
    assert featured_only_from_reply_data(by_hint) is True
    assert featured_only_from_reply_data(by_title) is True


def test_does_not_misfire_on_lookalikes():
    # web_selection 只认布尔 True；"精选" 二字出现在别处不算
    assert featured_only_from_reply_data({"control": {"web_selection": "true"}}) is False
    assert featured_only_from_reply_data({"control": {"root_input_text": "来条精选好评吧"}}) is False
    assert featured_only_from_reply_data({"cursor": {"name": "热门评论"}}) is False


@pytest.mark.parametrize("junk", [None, [], "x", 0, {}, {"control": None, "cursor": None}, {"control": []}])
def test_tolerates_junk(junk):
    assert featured_only_from_reply_data(junk) is False


def _page(data):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "{}"
    resp.json.return_value = {"code": 0, "data": data}
    return resp


def _adapter():
    a = BilibiliCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_fetch_by_mode_reports_featured_via_meta():
    sess = MagicMock()
    sess.get.side_effect = [_page(FEATURED)]
    meta: dict = {}
    comments, ok, err = _adapter()._fetch_comments_by_mode(sess, "123", mode=3, limit=20, meta=meta)
    assert (comments, ok, err) == ([], True, None)
    assert meta == {"featured_only": True}


def test_fetch_by_mode_meta_comes_from_first_page_only():
    first = {**NORMAL, "cursor": {"is_end": False, "next": 2, "name": "热门评论"}}
    # 第二页即使带了精选形状的 control 也不该改写首页结论
    second = {**FEATURED, "replies": [{"content": {"message": "二页"}, "member": {}, "like": 0}]}
    sess = MagicMock()
    sess.get.side_effect = [_page(first), _page(second)]
    meta: dict = {}
    comments, ok, _ = _adapter()._fetch_comments_by_mode(sess, "123", mode=3, limit=20, meta=meta)
    assert ok is True
    assert [c["text"] for c in comments] == ["路过", "二页"]
    assert meta == {"featured_only": False}


def _run_fetch(monkeypatch, data):
    a = _adapter()
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = [_page(data)]
    import curl_cffi.requests as cc

    monkeypatch.setattr(cc, "Session", lambda **kw: session)
    monkeypatch.setattr(a._breaker, "allow", lambda: True)
    monkeypatch.setattr(a._breaker, "record_success", lambda: None)
    monkeypatch.setattr(a._cookies, "pick", lambda: None)
    monkeypatch.setattr(a, "_resolve_aid", lambda *x, **k: "999")
    # id=None：与 mining 预筛的调用方式一致（绕过共享仓）
    task = MonitorTask(
        type="bilibili_comment", name="prefilter",
        target_url="https://www.bilibili.com/video/BV1rAeH6JE5k",
        config={"my_comment_text": "__csm_prefilter_noop__", "scrape_top_n": 20},
    )
    return a.fetch(task)


def test_fetch_puts_featured_only_into_metric(monkeypatch):
    """开了精选、还没精选任何评论：status=ok + 空 hot_comments + featured_only=True。"""
    result = _run_fetch(monkeypatch, FEATURED)
    assert result.status == "ok"
    assert result.metric["hot_comments"] == []
    assert result.metric["featured_only"] is True


def test_fetch_normal_video_has_no_featured_key(monkeypatch):
    result = _run_fetch(monkeypatch, NORMAL)
    assert result.status == "ok"
    assert [c["text"] for c in result.metric["hot_comments"]] == ["路过"]
    assert "featured_only" not in result.metric


def test_result_from_snapshot_skips_flag_on_error_snapshots():
    task = MonitorTask(type="bilibili_comment", name="t", target_url="u",
                       config={"my_comment_text": "hi"})
    failed = result_from_snapshot(
        task, CommentSnapshot(error="boom", featured_only=True), source="curl_cffi")
    assert failed.status == "failed"
    assert "featured_only" not in (failed.metric or {})
    ok = result_from_snapshot(task, CommentSnapshot(featured_only=True), source="curl_cffi")
    assert ok.metric["featured_only"] is True
