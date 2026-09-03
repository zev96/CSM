"""TikHub 关键词搜索响应 → VideoCard 归一化（真实 fixture，2026-09-01 实测抓取）。"""
import json
import logging
import pathlib

import pytest

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


def test_douyin_normalize_str_type_untrusted_but_matched():
    """type 字段未标注 untrusted：fixture 是 int，但实测偶发 str，统一 str() 比较。"""
    raw = _load("tikhub_search_douyin.json")
    for it in raw["data"]["business_data"]:
        it["type"] = "1" if it.get("type") == 1 else "66668"
    cards = N.normalize_douyin_search(raw, {"content_types": ["video"]})
    assert len(cards) == 3


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


def test_douyin_next_body_has_more_type_tolerant():
    """has_more 弱类型：1/"1"/True 都算"有下一页"，0/"0"/False/缺失都算没有。"""
    prev = N.douyin_first_body("k", {})
    for v in (1, "1", True):
        raw = {"data": {"business_config": {"has_more": v, "next_page": {"cursor": 8}}}}
        assert N.douyin_next_body(prev, raw) is not None, f"has_more={v!r} 应产出下一页"
    for v in (0, "0", False, None):
        cfg = {} if v is None else {"has_more": v}
        raw = {"data": {"business_config": {**cfg, "next_page": {"cursor": 8}}}}
        assert N.douyin_next_body(prev, raw) is None, f"has_more={v!r} 应为 None"


def test_douyin_next_body_none_on_stuck_cursor():
    """游标不动点：服务端回声同一个 cursor（has_more 却仍是 1），不能死循环重复拉页。"""
    prev = N.douyin_first_body("k", {})
    prev["cursor"] = 8
    raw = {"data": {"business_config": {"has_more": 1, "next_page": {"cursor": 8}}}}
    assert N.douyin_next_body(prev, raw) is None


def test_douyin_normalize_trusts_server_filter_when_content_type_not_all():
    """content_types=["note"] 时已下推 content_type=="2" 给服务端，本地全信任 —— 即使
    本地启发式（images/aweme_type）会误判成 video，也不能把服务端已筛好的结果滤掉。"""
    raw = {"data": {"business_data": [
        {"type": 1, "data": {"aweme_info": {
            "aweme_id": "123", "aweme_type": 0, "images": None,
            "author": {}, "statistics": {}, "video": {},
        }}},
    ]}}
    cards = N.normalize_douyin_search(raw, {"content_types": ["note"]})
    assert len(cards) == 1
    assert cards[0].platform_video_id == "123"


def test_douyin_normalize_logs_inner_error_code(caplog):
    with caplog.at_level(logging.WARNING):
        cards = N.normalize_douyin_search({"data": {"status_code": 8, "business_data": []}}, {})
    assert cards == []
    assert "8" in caplog.text


# ── B站 ─────────────────────────────────────────────────────────────────

def test_bilibili_first_params_pushes_order_and_date_range():
    p = N.bilibili_first_params("空气净化器", {
        "order": "pubdate", "time_begin": "2026-08-01", "time_end": "2026-08-31",
    })
    assert p["keyword"] == "空气净化器"
    assert p["order"] == "pubdate"
    assert p["page"] == 1 and p["page_size"] == 20
    assert isinstance(p["pubtime_begin_s"], int)
    assert isinstance(p["pubtime_end_s"], int)
    assert p["pubtime_end_s"] > p["pubtime_begin_s"]


def test_bilibili_first_params_defaults_and_bad_order():
    p = N.bilibili_first_params("k", {"order": "nonsense"})
    assert p["order"] == "totalrank"
    assert "pubtime_begin_s" not in p and "pubtime_end_s" not in p


def test_bilibili_normalize_real_fixture():
    raw = _load("tikhub_search_bilibili.json")
    cards = N.normalize_bilibili_search(raw, {})
    assert len(cards) == 3
    c = cards[0]
    assert c.platform == "bilibili"
    assert c.platform_video_id == "BV1w8Mr6VEfW"
    assert c.url == "https://www.bilibili.com/video/BV1w8Mr6VEfW"
    assert "<em" not in c.title and "空气净化器" in c.title      # <em> 高亮已 strip
    assert c.author_name == "科技先疯队"
    assert c.play_count == 173047 and c.like_count == 5297
    assert c.duration_sec == 11 * 60 + 28
    assert c.published_at == "2026-08-05T01:28:20Z"
    assert c.cover_url.startswith("https://")


def test_bilibili_normalize_count_string_fallback():
    """播放/点赞可能是展示态字符串（"1.2万"/"3,456"）—— 浏览器适配器一直有这层
    parse_int_count 兜底，TikHub 归一化不能丢。"""
    raw = {"data": {"data": {"result": [
        {"type": "video", "bvid": "BV1x", "title": "t", "author": "a", "mid": 1,
         "pic": "//i0.hdslb.com/x.jpg", "duration": "1:00",
         "play": "1.2万", "like": "3,456", "pubdate": 1620000000},
    ]}}}
    cards = N.normalize_bilibili_search(raw, {})
    assert len(cards) == 1
    assert cards[0].play_count == 12000
    assert cards[0].like_count == 3456


def test_bilibili_next_params_increments_until_numpages():
    raw = _load("tikhub_search_bilibili.json")            # page=1, numPages=50
    prev = N.bilibili_first_params("k", {})
    nxt = N.bilibili_next_params(prev, raw)
    assert nxt is not None and nxt["page"] == 2
    last = {"data": {"data": {"page": 50, "numPages": 50, "result": [{"type": "video"}]}}}
    assert N.bilibili_next_params({"page": 50}, last) is None
    empty = {"data": {"data": {"page": 1, "numPages": 50, "result": []}}}
    assert N.bilibili_next_params({"page": 1}, empty) is None


def test_bilibili_next_params_trusts_max_not_echoed_page():
    """服务端回声了一个不递增的 page（1），但我们本来就请求了第 2 页 —— 下一页必须
    是 3，不能被回声值拽回去重复拉第 2 页。"""
    prev = {"page": 2}
    raw = {"data": {"data": {"page": 1, "numPages": 50, "result": [{"type": "video"}]}}}
    nxt = N.bilibili_next_params(prev, raw)
    assert nxt is not None and nxt["page"] == 3


def test_bilibili_next_params_numpages_missing_relies_on_adapter_cap():
    """numPages 缺失或 0 时不拦截翻页——由 adapter 的 MAX_PAGES 兜底防止死循环。"""
    raw = {"data": {"data": {"page": 3, "result": [{"type": "video"}]}}}
    nxt = N.bilibili_next_params({"page": 3}, raw)
    assert nxt is not None and nxt["page"] == 4
    raw0 = {"data": {"data": {"page": 3, "numPages": 0, "result": [{"type": "video"}]}}}
    nxt0 = N.bilibili_next_params({"page": 3}, raw0)
    assert nxt0 is not None and nxt0["page"] == 4


def test_bilibili_normalize_logs_inner_error_code(caplog):
    with caplog.at_level(logging.WARNING):
        cards = N.normalize_bilibili_search({"data": {"code": -412, "data": {"result": []}}}, {})
    assert cards == []
    assert "-412" in caplog.text


# ── 快手 ────────────────────────────────────────────────────────────────

def test_kuaishou_first_params_keyword_only():
    assert N.kuaishou_first_params("k", {"time_begin": "2026-01-01"}) == {"keyword": "k", "pcursor": ""}


def test_kuaishou_normalize_real_fixture_skips_non_video_items():
    raw = _load("tikhub_search_kuaishou.json")
    cards = N.normalize_kuaishou_search(raw, {})
    # fixture：3 条 itemType==5 视频 + 1 条 itemType==28 相关搜索卡（必须跳过）
    assert len(cards) == 3
    c = cards[0]
    assert c.platform == "kuaishou"
    assert c.platform_video_id == "5226427428337552341"
    assert c.url == "https://www.kuaishou.com/short-video/5226427428337552341"
    assert c.title.startswith("空气净化器千万不要买")
    assert c.author_name == "恭喜的AI 科技"
    assert c.play_count == 141046 and c.like_count == 832
    assert c.duration_sec == 64                        # 64500ms → 64s
    assert c.published_at == "2021-12-27T11:11:59Z"    # 1640603519820ms


def test_kuaishou_normalize_local_time_filter_excludes_out_of_range():
    raw = _load("tikhub_search_kuaishou.json")
    # 首条发布于 2021-12-27；只要 2026 年的 → 应被本地后过滤掉，fixture 里恰好只有
    # 1 条落在 2026 年区间内。
    cards = N.normalize_kuaishou_search(raw, {"time_begin": "2026-01-01", "time_end": "2026-12-31"})
    assert all(c.platform_video_id != "5226427428337552341" for c in cards)
    assert len(cards) == 1


def test_kuaishou_next_params_pcursor_is_primary():
    """pcursor 是主判据；recoPcursor 不再是终止信号（曾误用，会导致相关搜索卡的推荐
    游标先耗尽就永久卡在第一页 —— 行为反转，见审查修复记录）。"""
    raw = _load("tikhub_search_kuaishou.json")           # pcursor="1", recoPcursor="no_more"
    assert N.kuaishou_next_params({"keyword": "k", "pcursor": ""}, raw) == {"keyword": "k", "pcursor": "1"}
    # pcursor 本身是 no_more → 停
    assert N.kuaishou_next_params({"keyword": "k"}, {"data": {"pcursor": "no_more", "mixFeeds": [1]}}) is None
    # pcursor 正常推进 → 继续（即使 recoPcursor 是别的值也不影响）
    more = {"data": {"pcursor": "2", "recoPcursor": "x", "mixFeeds": [{"itemType": 5}]}}
    assert N.kuaishou_next_params({"keyword": "k", "pcursor": ""}, more) == {"keyword": "k", "pcursor": "2"}
    # mixFeeds 为空 → 停
    empty_feeds = {"data": {"pcursor": "2", "mixFeeds": []}}
    assert N.kuaishou_next_params({"keyword": "k", "pcursor": ""}, empty_feeds) is None


def test_kuaishou_next_params_none_on_stuck_pcursor():
    """游标不动点：pcursor 与上次相同就不能死循环重复拉同一页。"""
    prev = {"keyword": "k", "pcursor": "5"}
    raw = {"data": {"pcursor": "5", "mixFeeds": [{"itemType": 5}]}}
    assert N.kuaishou_next_params(prev, raw) is None


def test_kuaishou_normalize_logs_inner_error_code(caplog):
    with caplog.at_level(logging.WARNING):
        cards = N.normalize_kuaishou_search({"data": {"responseCode": 109, "mixFeeds": []}}, {})
    assert cards == []
    assert "109" in caplog.text


# ── 快乐路径不产生告警 ────────────────────────────────────────────────────

def test_happy_path_fixtures_emit_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        N.normalize_douyin_search(_load("tikhub_search_douyin.json"), {"content_types": ["video"]})
        N.normalize_bilibili_search(_load("tikhub_search_bilibili.json"), {})
        N.normalize_kuaishou_search(_load("tikhub_search_kuaishou.json"), {})
    assert caplog.text == ""


# ── I3：畸形 payload 永不抛异常 ────────────────────────────────────────────

_MALFORMED_RAW = [
    [],
    "str",
    {"data": []},
    {"data": "x"},
    {"data": {"data": []}},
    {"data": {"business_data": "x"}},
    {"data": {"mixFeeds": [{"itemType": 5, "feed": []}]}},
]


@pytest.mark.parametrize("raw", _MALFORMED_RAW)
def test_never_raises_on_malformed_raw_payloads(raw):
    dy_prev = {"keyword": "k", "cursor": 0, "search_id": "", "backtrace": "", "content_type": "1"}
    dy_next = N.douyin_next_body(dy_prev, raw)
    assert dy_next is None or isinstance(dy_next, dict)
    assert N.normalize_douyin_search(raw, {}) == []

    bl_next = N.bilibili_next_params({"page": 1}, raw)
    assert bl_next is None or isinstance(bl_next, dict)
    assert N.normalize_bilibili_search(raw, {}) == []

    ks_next = N.kuaishou_next_params({"keyword": "k", "pcursor": ""}, raw)
    assert ks_next is None or isinstance(ks_next, dict)
    assert N.normalize_kuaishou_search(raw, {}) == []


@pytest.mark.parametrize("weird", [None, []])
def test_first_body_never_raises_on_weird_filters(weird):
    assert isinstance(N.douyin_first_body("k", weird), dict)
    assert isinstance(N.bilibili_first_params("k", weird), dict)
    assert isinstance(N.kuaishou_first_params("k", weird), dict)


def test_bilibili_next_params_defaults_on_non_numeric_fields():
    p = N.bilibili_next_params(
        {"page": "abc"},
        {"data": {"data": {"page": "zz", "numPages": "q", "result": [1]}}},
    )
    assert isinstance(p, dict) and p["page"] == 2


def test_kuaishou_normalize_tolerates_non_numeric_duration():
    raw = _load("tikhub_search_kuaishou.json")
    for it in raw["data"]["mixFeeds"]:
        if str(it.get("itemType")) == "5":
            it["feed"]["duration"] = "abc"
    cards = N.normalize_kuaishou_search(raw, {})
    assert len(cards) == 3 and all(c.duration_sec is None for c in cards)


def test_douyin_next_body_stuck_cursor_detected_across_types():
    prev = dict(N.douyin_first_body("k", {}))
    prev["cursor"] = 8
    raw = {"data": {"business_config": {"has_more": 1, "backtrace": "b",
                                        "next_page": {"cursor": "8", "search_id": "s"}}}}
    assert N.douyin_next_body(prev, raw) is None       # int 8 vs str "8" 也算不动点
