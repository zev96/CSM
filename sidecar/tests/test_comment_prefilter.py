"""Tests for csm_core.mining.comment_prefilter.

Pure unit tests — no network, no browser, no sidecar imports.
Monkeypatches the adapter registry used by fetch_video_comment_texts.
"""
from __future__ import annotations
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from csm_core.monitor.base import MonitorResult


# ---------------------------------------------------------------------------
# count_brand_hits
# ---------------------------------------------------------------------------

def test_count_brand_hits_basic():
    from csm_core.mining.comment_prefilter import count_brand_hits

    texts = ["买了石头很好", "凑数评论", "roborock yyds"]
    assert count_brand_hits(texts, ["石头", "roborock"]) == 2


def test_count_brand_hits_empty_brands():
    from csm_core.mining.comment_prefilter import count_brand_hits

    assert count_brand_hits(["任意文本", "another"], []) == 0


def test_count_brand_hits_case_insensitive():
    from csm_core.mining.comment_prefilter import count_brand_hits

    assert count_brand_hits(["Roborock good"], ["roborock"]) == 1


def test_count_brand_hits_blank_brand_ignored():
    """Brands that are empty strings or whitespace-only are ignored."""
    from csm_core.mining.comment_prefilter import count_brand_hits

    # blank brand should not match anything
    assert count_brand_hits(["hello world"], [" ", ""]) == 0


def test_count_brand_hits_multiple_brands_same_text_counts_once():
    """A single text containing multiple brands is counted once, not per-brand."""
    from csm_core.mining.comment_prefilter import count_brand_hits

    # "石头 roborock 都提到了" hits both brands — text counted once
    assert count_brand_hits(["石头 roborock 都提到了"], ["石头", "roborock"]) == 1


# ---------------------------------------------------------------------------
# fetch_video_comment_texts
# ---------------------------------------------------------------------------

def _make_ok_result(texts: list[str]) -> MonitorResult:
    hot = [{"rank": i + 1, "text": t, "author": "u", "likes": 0} for i, t in enumerate(texts)]
    return MonitorResult(
        task_id=0,
        checked_at=datetime.utcnow(),
        status="ok",
        rank=-1,
        metric={"hot_comments": hot},
    )


def _make_failed_result() -> MonitorResult:
    return MonitorResult(
        task_id=0,
        checked_at=datetime.utcnow(),
        status="failed",
        rank=-1,
        metric={},
    )


def test_fetch_video_comment_texts_ok(monkeypatch):
    """When the adapter returns status=ok, texts are extracted from hot_comments."""
    from csm_core.mining import comment_prefilter as mod

    fake_adapter = MagicMock()
    fake_adapter.fetch.return_value = _make_ok_result(["a", "b"])
    fake_all = {
        "douyin_comment": fake_adapter,
        "bilibili_comment": MagicMock(),
        "kuaishou_comment": MagicMock(),
    }
    with patch.dict("csm_core.monitor.platforms.ALL", fake_all, clear=False):
        # Reload the registry reference inside the function by patching the import
        result = mod.fetch_video_comment_texts("douyin", "https://v.douyin.com/fake", limit=10)

    assert result == ["a", "b"]


def test_fetch_video_comment_texts_status_failed(monkeypatch):
    """A status=failed result → []."""
    from csm_core.mining import comment_prefilter as mod

    fake_adapter = MagicMock()
    fake_adapter.fetch.return_value = _make_failed_result()
    fake_all = {"bilibili_comment": fake_adapter}
    with patch.dict("csm_core.monitor.platforms.ALL", fake_all, clear=False):
        result = mod.fetch_video_comment_texts("bilibili", "https://b.bilibili.com/fake", limit=10)

    assert result == []


def test_fetch_video_comment_texts_adapter_raises(monkeypatch):
    """If the adapter raises, return [] (fail-open)."""
    from csm_core.mining import comment_prefilter as mod

    fake_adapter = MagicMock()
    fake_adapter.fetch.side_effect = RuntimeError("network error")
    fake_all = {"kuaishou_comment": fake_adapter}
    with patch.dict("csm_core.monitor.platforms.ALL", fake_all, clear=False):
        result = mod.fetch_video_comment_texts("kuaishou", "https://www.kuaishou.com/fake", limit=10)

    assert result == []


def test_fetch_video_comment_texts_unknown_platform():
    """Unknown platform → [] immediately (no adapter lookup)."""
    from csm_core.mining.comment_prefilter import fetch_video_comment_texts

    result = fetch_video_comment_texts("weibo", "https://weibo.com/fake", limit=5)
    assert result == []


def test_fetch_video_comment_texts_passes_limit(monkeypatch):
    """scrape_top_n in the task config should reflect the limit argument."""
    from csm_core.mining import comment_prefilter as mod

    fake_adapter = MagicMock()
    fake_adapter.fetch.return_value = _make_ok_result(["x"])

    captured_tasks = []

    def capture_fetch(task):
        captured_tasks.append(task)
        return _make_ok_result(["x"])

    fake_adapter.fetch.side_effect = capture_fetch
    fake_all = {"douyin_comment": fake_adapter}
    with patch.dict("csm_core.monitor.platforms.ALL", fake_all, clear=False):
        mod.fetch_video_comment_texts("douyin", "https://v.douyin.com/fake", limit=42)

    assert captured_tasks[0].config["scrape_top_n"] == 42


# ---------------------------------------------------------------------------
# Regression: _PREFILTER_PLACEHOLDER must pass build_match_result's guard
# ---------------------------------------------------------------------------

def test_prefilter_placeholder_passes_build_match_guard():
    # 确保占位 my_comment_text strip 后非空 —— 否则 build_match_result 返回 failed，
    # fetch_video_comment_texts 永远返回 []（mock fetch 的测试发现不了）。
    from csm_core.monitor.platforms._comment_common import build_match_result
    from csm_core.monitor.base import MonitorTask
    from csm_core.mining.comment_prefilter import _PREFILTER_PLACEHOLDER

    task = MonitorTask(
        type="bilibili_comment",
        name="t",
        target_url="u",
        config={"my_comment_text": _PREFILTER_PLACEHOLDER},
    )
    comments = [
        {"rank": 1, "text": "买了石头很好", "author": "a", "likes": 1},
        {"rank": 2, "text": "凑数", "author": "b", "likes": 0},
    ]
    res = build_match_result(task, comments, source="test")
    assert res.status == "ok"
    assert [c["text"] for c in res.metric["hot_comments"]] == ["买了石头很好", "凑数"]
