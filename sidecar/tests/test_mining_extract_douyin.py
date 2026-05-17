import json
from pathlib import Path

from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "douyin" / "search_response.json"


def test_extract_two_cards_from_fixture():
    adapter = DouyinSearchAdapter()
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards = adapter._extract_cards(body)
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "douyin"
    assert c1.platform_video_id == "7300000000000000001"
    assert c1.url == "https://www.douyin.com/video/7300000000000000001"
    assert c1.title == "扫地机器人推荐"
    assert c1.author_name == "测评博主"
    assert c1.author_id == "123"
    assert c1.like_count == 1234     # digg_count
    assert c1.play_count == 5678
    assert c1.duration_sec == 60     # 60000ms → 60s
    assert c1.cover_url.startswith("https://")


def test_extract_handles_missing_fields():
    adapter = DouyinSearchAdapter()
    cards = adapter._extract_cards({
        "status_code": 0,
        "data": [{"type": 1, "aweme_info": {"aweme_id": "x"}}],
    })
    assert len(cards) == 1
    assert cards[0].platform_video_id == "x"
    assert cards[0].title == ""
    assert cards[0].duration_sec is None


def test_extract_returns_empty_on_failure_status():
    adapter = DouyinSearchAdapter()
    cards = adapter._extract_cards({"status_code": 8, "data": []})
    # Adapter is forgiving on status when data is empty anyway.
    assert cards == []
