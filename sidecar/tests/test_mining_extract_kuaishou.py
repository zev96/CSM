"""Tests for ``KuaishouSearchAdapter._feed_to_card``.

The Kuaishou adapter migrated from DOM scraping to a direct GraphQL POST
against ``/graphql`` (visionSearchPhoto). See FEASIBILITY_ANALYSIS.md
§1.2 / §2 阶段 3 for the rationale.

These are pure unit tests against a synthetic feed dict. End-to-end
exercise against the live Kuaishou GraphQL endpoint lives elsewhere
(integration smoke).
"""
from __future__ import annotations

from typing import Any

from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter


def _sample_feed(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": 1,
        "author": {
            "id": "user_abc",
            "name": "家电达人",
            "headerUrl": "https://avatar.example/u.jpg",
        },
        "photo": {
            "id": "3xabc123",
            "caption": "扫地机器人 推荐",
            "duration": 83_000,            # 83 s, in milliseconds
            "viewCount": 123_000,
            "likeCount": 3_456,
            "commentCount": 50,
            "coverUrl": "https://cover.example/abc.jpg",
            "timestamp": 1_700_000_000_000,  # 2023-11-14, in ms
        },
    }
    base.update(overrides)
    return base


def test_feed_to_card_typical():
    adapter = KuaishouSearchAdapter()
    card = adapter._feed_to_card(_sample_feed(), rank=1)
    assert card is not None
    assert card.platform == "kuaishou"
    assert card.platform_video_id == "3xabc123"
    assert card.url == "https://www.kuaishou.com/short-video/3xabc123"
    assert card.title == "扫地机器人 推荐"
    assert card.author_name == "家电达人"
    assert card.author_id == "user_abc"
    assert card.cover_url == "https://cover.example/abc.jpg"
    assert card.duration_sec == 83        # 83000 ms → 83 s
    assert card.play_count == 123_000
    assert card.like_count == 3_456
    assert card.published_at is not None  # not exact UTC string, just present
    assert card.rank_in_search == 1


def test_feed_to_card_missing_photo_id_returns_none():
    adapter = KuaishouSearchAdapter()
    feed = _sample_feed()
    feed["photo"].pop("id")
    assert adapter._feed_to_card(feed, rank=1) is None


def test_feed_to_card_missing_author_safe():
    adapter = KuaishouSearchAdapter()
    feed = _sample_feed()
    feed.pop("author")
    card = adapter._feed_to_card(feed, rank=2)
    assert card is not None
    assert card.author_name == ""
    assert card.author_id == ""
    assert card.rank_in_search == 2


def test_feed_to_card_origin_caption_fallback():
    adapter = KuaishouSearchAdapter()
    feed = _sample_feed()
    feed["photo"]["caption"] = ""
    feed["photo"]["originCaption"] = "原文标题"
    card = adapter._feed_to_card(feed, rank=3)
    assert card is not None
    assert card.title == "原文标题"


def test_feed_to_card_handles_zero_duration_and_timestamp():
    adapter = KuaishouSearchAdapter()
    feed = _sample_feed()
    feed["photo"]["duration"] = 0
    feed["photo"]["timestamp"] = 0
    card = adapter._feed_to_card(feed, rank=4)
    assert card is not None
    assert card.duration_sec is None
    assert card.published_at is None


def test_feed_to_card_returns_none_on_non_dict():
    adapter = KuaishouSearchAdapter()
    assert adapter._feed_to_card("not a feed", rank=1) is None  # type: ignore[arg-type]
    assert adapter._feed_to_card(None, rank=1) is None  # type: ignore[arg-type]
