"""三评论适配器的翻页进度上报 + scrape_top_n 抓取上限。

锁定行为：适配器每抓完一页应调用 progress_cb(已抓数, 目标数)，序列单调
不减；fetch() 把 task.config.scrape_top_n 当抓取上限传给翻页函数。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from csm_core.monitor.platforms.bilibili_comment import BilibiliCommentAdapter
from csm_core.monitor.platforms.douyin_comment import DouyinCommentAdapter


def _bili_page(replies, *, is_end, next_cursor=0):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "{}"
    resp.json.return_value = {
        "code": 0,
        "data": {
            "replies": [
                {"content": {"message": m}, "member": {"uname": "u"}, "like": 1}
                for m in replies
            ],
            "cursor": {"is_end": is_end, "next": next_cursor},
        },
    }
    return resp


def _bili_adapter():
    a = BilibiliCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_bilibili_fetch_reports_progress_per_page():
    sess = MagicMock()
    sess.get.side_effect = [
        _bili_page(["a", "b"], is_end=False, next_cursor=10),
        _bili_page(["c"], is_end=True),
    ]
    calls = []
    a = _bili_adapter()
    comments, ok, err = a._fetch_comments_by_mode(
        sess, "123", mode=2, limit=150,
        progress_cb=lambda c, t: calls.append((c, t)),
    )
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b", "c"]
    # 每页一次，current 单调递增，total 恒为 limit
    assert calls == [(2, 150), (3, 150)]


def test_bilibili_fetch_uses_scrape_top_n_as_limit(monkeypatch):
    """fetch() 应把 task.config.scrape_top_n 当抓取上限。"""
    from csm_core.monitor.base import MonitorTask

    a = _bili_adapter()
    captured = {}

    def fake_fetch_mode(session, aid, mode, limit, cancel_token=None, progress_cb=None):
        captured["limit"] = limit
        return [], True, None

    # Stub out infrastructure that requires DB / network
    monkeypatch.setattr(a._breaker, "allow", lambda: True)
    monkeypatch.setattr(a._breaker, "record_success", lambda: None)
    monkeypatch.setattr(a._cookies, "pick", lambda: None)
    monkeypatch.setattr(a, "_resolve_aid", lambda *x, **k: "999")
    monkeypatch.setattr(a, "_fetch_comments_by_mode", fake_fetch_mode)
    task = MonitorTask(
        id=1, type="bilibili_comment", name="t",
        target_url="https://www.bilibili.com/video/BV1xx",
        config={"my_comment_text": "hi", "scrape_top_n": 40},
    )
    a.fetch(task, progress_cb=None)
    assert captured["limit"] == 40


def _douyin_page(texts, *, has_more, cursor=0):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "comments": [
            {"text": t, "user": {"nickname": "n"}, "digg_count": 1} for t in texts
        ],
        "has_more": has_more,
        "cursor": cursor,
    }
    return resp


def _douyin_adapter():
    a = DouyinCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_douyin_fetch_reports_progress_per_page():
    sess = MagicMock()
    sess.get.side_effect = [
        _douyin_page(["a", "b"], has_more=1, cursor=20),
        _douyin_page(["c"], has_more=0),
    ]
    calls = []
    a = _douyin_adapter()
    comments, ok, err = a._fetch_comments(
        sess, "7xxx", limit=150,
        progress_cb=lambda c, t: calls.append((c, t)),
    )
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b", "c"]
    assert calls == [(2, 150), (3, 150)]


from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter


def _ks_page(texts, *, pcursor_v2):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "data": {
            "visionCommentList": {
                "rootCommentsV2": [
                    {"commentId": f"c{i}", "content": t, "authorName": "a", "likedCount": 0}
                    for i, t in enumerate(texts)
                ],
                "rootComments": [],
                "pcursorV2": pcursor_v2,
                "pcursor": "no_more",
            }
        }
    }
    return resp


def _ks_adapter():
    a = KuaishouCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_kuaishou_fetch_reports_progress_per_page():
    sess = MagicMock()
    sess.post.side_effect = [
        _ks_page(["a", "b"], pcursor_v2="next"),
        _ks_page(["c"], pcursor_v2="no_more"),
    ]
    calls = []
    a = _ks_adapter()
    comments, ok, err = a._fetch_comments(
        sess, "photo1", limit=150,
        progress_cb=lambda c, t: calls.append((c, t)),
    )
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b", "c"]
    assert calls == [(2, 150), (3, 150)]


def test_kuaishou_fetch_uses_scrape_top_n_as_limit(monkeypatch):
    """fetch() 应把 task.config.scrape_top_n 当抓取上限（对齐 B站 test）。"""
    from csm_core.monitor.base import MonitorTask

    a = _ks_adapter()
    captured = {}

    def fake_fetch(session, photo_id, limit, cancel_token=None, progress_cb=None):
        captured["limit"] = limit
        return [], True, None

    monkeypatch.setattr(a, "_extract_video_id", lambda *x, **k: ("photo1", ""))
    monkeypatch.setattr(a, "_fetch_comments", fake_fetch)
    a._breaker.allow = lambda: True
    a._breaker.record_success = lambda: None
    a._cookies.pick = lambda: None
    task = MonitorTask(
        id=1, type="kuaishou_comment", name="t",
        target_url="https://www.kuaishou.com/short-video/abc",
        config={"my_comment_text": "hi", "scrape_top_n": 40},
    )
    a.fetch(task, progress_cb=None)
    assert captured["limit"] == 40
