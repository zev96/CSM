"""TikHub 关键词搜索响应 → VideoCard 归一化（真实 fixture，2026-09-01 实测抓取）。"""
import json
import pathlib

from csm_core.mining.platforms import tikhub_normalize as N

FIX = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ── 抖音 ────────────────────────────────────────────────────────────────

def test_douyin_first_body_pushes_filters_down():
    body = N.douyin_first_body("空气净化器", {
        "publish_time": "182", "sort_type": "1", "content_types": ["video"],
    })
    assert body == {
        "keyword": "空气净化器", "cursor": 0, "search_id": "", "backtrace": "",
        "sort_type": "1", "publish_time": "180", "content_type": "1",
    }


def test_douyin_first_body_content_type_mapping():
    assert N.douyin_first_body("k", {"content_types": ["note"]})["content_type"] == "2"
    assert N.douyin_first_body("k", {"content_types": ["video", "note"]})["content_type"] == "0"
    assert N.douyin_first_body("k", {})["content_type"] == "1"          # 缺省=仅视频


def test_douyin_normalize_real_fixture_filters_non_video_cards():
    raw = _load("tikhub_search_douyin.json")
    cards = N.normalize_douyin_search(raw, {"content_types": ["video"]})
    # fixture 里 business_data 4 项：3 张 type==1 视频卡 + 1 张 type==66668 非视频卡
    assert len(cards) == 3
    c = cards[0]
    assert c.platform == "douyin"
    assert c.platform_video_id == "7454425478926060809"
    assert c.author_name == "秋叶"
    assert c.like_count == 3936
    assert c.duration_sec == 142
    assert c.published_at == "2024-12-31T09:01:37Z"
    assert c.url.startswith("https://")


def test_douyin_next_body_reads_business_config():
    raw = _load("tikhub_search_douyin.json")
    prev = N.douyin_first_body("k", {})
    nxt = N.douyin_next_body(prev, raw)
    assert nxt is not None
    assert nxt["cursor"] == 8
    assert nxt["search_id"] == "202609012007081FFCE74A7B89BE04E03E"
    assert nxt["backtrace"]                         # 非空字符串
    assert nxt["keyword"] == "k" and nxt["content_type"] == prev["content_type"]


def test_douyin_next_body_none_when_no_more():
    raw = {"data": {"business_config": {"has_more": 0}}}
    assert N.douyin_next_body(N.douyin_first_body("k", {}), raw) is None
    assert N.douyin_next_body(N.douyin_first_body("k", {}), {"data": {}}) is None
