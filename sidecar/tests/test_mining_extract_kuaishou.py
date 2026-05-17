from pathlib import Path

from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "kuaishou" / "search_dom.html"


def test_extract_two_cards_from_fixture():
    adapter = KuaishouSearchAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    cards = adapter._extract_from_dom(html, exclude_ids=set())
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "kuaishou"
    assert c1.platform_video_id == "3xabc123"
    assert c1.url == "https://www.kuaishou.com/short-video/3xabc123"
    assert c1.title == "扫地机器人 推荐"
    assert c1.author_name == "家电达人"
    assert c1.play_count == 123_000   # 12.3万
    assert c1.like_count == 3_456
    assert c1.duration_sec == 83      # 1:23


def test_extract_respects_exclude_ids():
    adapter = KuaishouSearchAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    cards = adapter._extract_from_dom(html, exclude_ids={"3xabc123"})
    assert len(cards) == 1
    assert cards[0].platform_video_id == "3xdef456"
