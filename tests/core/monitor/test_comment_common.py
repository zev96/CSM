"""Tests for the shared comment-retention match logic."""
from __future__ import annotations
import pytest

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms._comment_common import (
    DEFAULT_SCRAPE_TOP_N,
    build_match_result,
)


def _make_task(my_text: str, top_n: int = 5, **extra):
    return MonitorTask(
        id=1,
        type="kuaishou_comment",
        name="t",
        target_url="https://example.com",
        config={"my_comment_text": my_text, "top_n": top_n, **extra},
    )


def _comments(texts: list[str]) -> list[dict]:
    """Helper: build hot_comments shape returned by adapters."""
    return [
        {"rank": i + 1, "text": t, "author": f"u{i + 1}"}
        for i, t in enumerate(texts)
    ]


def test_match_within_alert_top_n_returns_actual_rank():
    """Comment at position 3, alert_top_n=5 → rank=3, matched=True."""
    comments = _comments(["other1", "other2", "我的评论 完整原文", "other4"])
    task = _make_task(my_text="我的评论 完整原文", top_n=5)
    res = build_match_result(task, comments, source="test")
    assert res.rank == 3
    assert res.metric["matched"] is True
    assert res.metric["alert_top_n"] == 5
    assert res.metric["scrape_top_n"] == DEFAULT_SCRAPE_TOP_N


def test_match_beyond_alert_top_n_but_within_scrape_returns_actual_rank():
    """Comment at position 20, alert_top_n=5 → rank=20 (not -1).

    This is the bug-fix the user reported: previously [:top_n] sliced to
    just top 5 and missed comments at position 20. Now we scan up to 150
    and return the real position so the UI can show "fell out of ideal
    range" instead of "comment lost".
    """
    other = ["unrelated comment"] * 19
    comments = _comments(other + ["我的评论 原文"])
    task = _make_task(my_text="我的评论 原文", top_n=5)
    res = build_match_result(task, comments, source="test")
    assert res.rank == 20
    assert res.metric["matched"] is True
    assert res.metric["scope_total"] == 20  # only 20 fetched


def test_no_match_returns_minus_one():
    """Comment text not present anywhere in scope → rank=-1."""
    comments = _comments(["unrelated 1", "unrelated 2", "unrelated 3"])
    task = _make_task(my_text="完全不在评论区的话", top_n=5)
    res = build_match_result(task, comments, source="test")
    assert res.rank == -1
    assert res.metric["matched"] is False


def test_alert_top_n_does_not_clip_search_window():
    """alert_top_n=5 + scrape default 150 + comment at rank 80 → still finds it."""
    # 80 noise + 1 target + more noise to total 100
    seq = ["noise"] * 79 + ["我的评论 关键内容"] + ["noise"] * 20
    comments = _comments(seq)
    task = _make_task(my_text="我的评论 关键内容", top_n=5)
    res = build_match_result(task, comments, source="test")
    assert res.rank == 80


def test_scrape_top_n_default_caps_at_150():
    """Beyond position 150 → not found (matches user's '150 以外' requirement)."""
    # Put target at position 151
    seq = ["noise distinct"] * 150 + ["我独一无二的评论"] + ["noise distinct"] * 20
    comments = _comments(seq)
    task = _make_task(my_text="我独一无二的评论", top_n=5)
    res = build_match_result(task, comments, source="test")
    # rank should be -1 because we only scan first 150
    assert res.rank == -1
    assert res.metric["scope_total"] == 150


def test_missing_my_comment_text_returns_failed():
    task = _make_task(my_text="", top_n=5)
    res = build_match_result(task, _comments(["x"]), source="test")
    assert res.status == "failed"
    assert "my_comment_text" in res.error_message


def test_report_progress_noop_when_cb_none():
    from csm_core.monitor.platforms._comment_common import report_progress
    # None cb 不应抛错
    report_progress(None, 3, 10)


def test_report_progress_forwards_current_total():
    from csm_core.monitor.platforms._comment_common import report_progress
    calls = []
    report_progress(lambda c, t: calls.append((c, t)), 5, 150)
    assert calls == [(5, 150)]


def test_report_progress_swallows_cb_exception():
    from csm_core.monitor.platforms._comment_common import report_progress

    def boom(c, t):
        raise RuntimeError("sink down")

    # 上报失败绝不能打断抓取
    report_progress(boom, 1, 2)
