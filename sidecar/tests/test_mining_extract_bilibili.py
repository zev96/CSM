import json
from pathlib import Path

from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "bilibili" / "search_response.json"


def test_extract_cards_basic():
    adapter = BilibiliSearchAdapter()
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards = adapter._extract_cards(body)
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "bilibili"
    assert c1.platform_video_id == "BV1abc23defg"
    assert c1.url == "https://www.bilibili.com/video/BV1abc23defg"
    assert c1.title == "扫地机器人选购指南"
    assert c1.author_name == "测评UP主"
    assert c1.author_id == "88888888"
    assert c1.duration_sec == 623   # 10:23
    assert c1.play_count == 12345
    assert c1.cover_url.startswith("https://")


def test_extract_handles_em_tags():
    adapter = BilibiliSearchAdapter()
    cards = adapter._extract_cards({
        "code": 0,
        "data": {"result": [{
            "type": "video", "bvid": "BVa", "title": "<em class=\"keyword\">扫地</em>机器人",
            "author": "x", "mid": 1, "pic": "//x", "duration": "0:30",
            "play": 1, "like": 1, "pubdate": 0,
        }]},
    })
    assert cards[0].title == "扫地机器人"


def test_extract_skips_non_video_results():
    adapter = BilibiliSearchAdapter()
    cards = adapter._extract_cards({
        "code": 0,
        "data": {"result": [
            {"type": "bili_user", "mid": 1},
            {"type": "video", "bvid": "BVa", "title": "x", "author": "a", "mid": 1,
             "pic": "//x", "duration": "0:10", "play": 1, "like": 1, "pubdate": 0},
        ]},
    })
    assert len(cards) == 1
    assert cards[0].platform_video_id == "BVa"


def test_extract_returns_empty_on_error_code():
    adapter = BilibiliSearchAdapter()
    cards = adapter._extract_cards({"code": -101, "data": None})
    assert cards == []
