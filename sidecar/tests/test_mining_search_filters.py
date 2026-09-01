"""P1 搜索筛选参数测试：URL/参数构建纯函数 + v13 存储往返。

平台适配器的网络/浏览器路径不在这里测 —— 只测能纯函数化的部分：
抖音 URL 构建与图文过滤、B 站额外参数、日期区间辅助、storage 往返。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    yield


# ---------------------------------------------------------------------------
# _common 日期辅助
# ---------------------------------------------------------------------------

def test_date_to_epoch_roundtrip():
    from csm_core.mining.platforms._common import date_to_epoch

    begin = date_to_epoch("2026-08-01")
    end = date_to_epoch("2026-08-01", end_of_day=True)
    assert begin is not None and end is not None
    assert end - begin == 23 * 3600 + 59 * 60 + 59
    # 本地时区当天 00:00:00
    assert datetime.fromtimestamp(begin).hour == 0


def test_date_to_epoch_invalid():
    from csm_core.mining.platforms._common import date_to_epoch

    assert date_to_epoch(None) is None
    assert date_to_epoch("") is None
    assert date_to_epoch("not-a-date") is None
    assert date_to_epoch("2026/08/01") is None


def test_iso_within_epoch_range():
    from csm_core.mining.platforms._common import date_to_epoch, iso_within_epoch_range

    begin = date_to_epoch("2026-08-01")
    end = date_to_epoch("2026-08-31", end_of_day=True)
    # 区间中/前/后各构造一个 UTC ISO 时间戳
    from datetime import timezone as _tz
    mid = datetime.fromtimestamp(begin + 10 * 86400, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = datetime.fromtimestamp(begin - 86400, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    after = datetime.fromtimestamp(end + 86400, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert iso_within_epoch_range(mid, begin, end) is True
    assert iso_within_epoch_range(before, begin, end) is False
    assert iso_within_epoch_range(after, begin, end) is False
    # 端点为 None = 不设限
    assert iso_within_epoch_range(before, None, end) is True
    assert iso_within_epoch_range(after, begin, None) is True
    # fail-open：published_at 缺失/坏格式 → 保留
    assert iso_within_epoch_range(None, begin, end) is True
    assert iso_within_epoch_range("garbage", begin, end) is True
    # 完全无区间 → 恒 True
    assert iso_within_epoch_range(None, None, None) is True


# ---------------------------------------------------------------------------
# 抖音 URL 构建 + 图文过滤
# ---------------------------------------------------------------------------

def test_douyin_build_url_defaults_unchanged():
    """默认筛选 → 与旧行为字节级一致（?type=video，无其它参数）。"""
    from csm_core.mining.platforms.douyin_search import _build_search_url

    url = _build_search_url("吸尘器", {})
    assert url == "https://www.douyin.com/search/%E5%90%B8%E5%B0%98%E5%99%A8?type=video"


def test_douyin_build_url_with_filters():
    from csm_core.mining.platforms.douyin_search import _build_search_url

    url = _build_search_url("kw", {
        "publish_time": "7", "sort_type": "2", "content_types": ["video"],
    })
    assert "type=video" in url
    assert "publish_time=7" in url
    assert "sort_type=2" in url


def test_douyin_build_url_note_goes_general_search():
    """含图文 → 综合搜索（无 type=video）。"""
    from csm_core.mining.platforms.douyin_search import _build_search_url

    url = _build_search_url("kw", {"content_types": ["video", "note"]})
    assert "type=video" not in url
    url2 = _build_search_url("kw", {"content_types": ["note"]})
    assert "type=video" not in url2


def _dy_body(items):
    return {"status_code": 0, "data": items}


def _dy_video_item(aweme_id="111"):
    return {"aweme_info": {
        "aweme_id": aweme_id, "desc": "视频",
        "author": {"nickname": "a", "uid": "1"},
        "statistics": {"play_count": 10, "digg_count": 2},
        "video": {"cover": {"url_list": ["c"]}, "duration": 15000},
        "create_time": 1756600000,
    }}


def _dy_note_item(aweme_id="222"):
    return {"aweme_info": {
        "aweme_id": aweme_id, "desc": "图文",
        "aweme_type": 68,
        "images": [{"url_list": ["i"]}],
        "author": {"nickname": "b", "uid": "2"},
        "statistics": {"play_count": 5, "digg_count": 1},
        "video": {},
        "create_time": 1756600000,
    }}


def test_douyin_extract_cards_filters_content_type():
    from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter

    adapter = DouyinSearchAdapter()
    body = _dy_body([_dy_video_item(), _dy_note_item()])

    both = adapter._extract_cards(body)
    assert {c.platform_video_id for c in both} == {"111", "222"}

    only_video = adapter._extract_cards(body, allowed_types=frozenset({"video"}))
    assert [c.platform_video_id for c in only_video] == ["111"]

    only_note = adapter._extract_cards(body, allowed_types=frozenset({"note"}))
    assert [c.platform_video_id for c in only_note] == ["222"]
    # 图文的 fallback URL 用 /note/ 路径
    assert only_note[0].url.endswith("/note/222")


# ---------------------------------------------------------------------------
# B 站额外参数
# ---------------------------------------------------------------------------

def test_bilibili_filter_params_defaults_empty():
    from csm_core.mining.platforms.bilibili_search import _build_filter_params

    assert _build_filter_params({}) == {}
    assert _build_filter_params({"order": "totalrank"}) == {}


def test_bilibili_filter_params_full():
    from csm_core.mining.platforms._common import date_to_epoch
    from csm_core.mining.platforms.bilibili_search import _build_filter_params

    params = _build_filter_params({
        "order": "pubdate", "time_begin": "2026-08-01", "time_end": "2026-08-31",
    })
    assert params["order"] == "pubdate"
    assert params["pubtime_begin_s"] == date_to_epoch("2026-08-01")
    assert params["pubtime_end_s"] == date_to_epoch("2026-08-31", end_of_day=True)


def test_bilibili_filter_params_invalid_ignored():
    from csm_core.mining.platforms.bilibili_search import _build_filter_params

    params = _build_filter_params({"order": "hacked", "time_begin": "bad-date"})
    assert params == {}


# ---------------------------------------------------------------------------
# storage v13：filters 往返 + 热评快照
# ---------------------------------------------------------------------------

def test_v13_columns_exist(db):
    conn = ms.get_conn()
    job_cols = {r[1] for r in conn.execute("PRAGMA table_info(mining_jobs)").fetchall()}
    video_cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()}
    assert "filters_json" in job_cols
    assert "top_comments_json" in video_cols


def test_v13_migration_idempotent(db):
    conn = ms.get_conn()
    ms.apply_v13_migration(conn)  # 二次执行不抛错
    ms.apply_v13_migration(conn)


def test_create_job_filters_roundtrip(db):
    filters = {
        "douyin": {"publish_time": "7", "sort_type": "0", "content_types": ["video", "note"]},
        "bilibili": {"order": "click", "time_begin": "2026-08-01", "time_end": None},
        "kuaishou": {"time_begin": None, "time_end": None},
    }
    jid = ms.create_job("kw", ["douyin"], 50, filters=filters)
    job = ms.get_job(jid)
    assert job["filters"] == filters


def test_create_job_without_filters_defaults_empty(db):
    jid = ms.create_job("kw", ["douyin"], 50)
    job = ms.get_job(jid)
    assert job["filters"] == {}


def test_set_top_comments_roundtrip(db):
    from csm_core.mining.models import VideoCard

    jid = ms.create_job("kw", ["bilibili"], 50)
    vid = ms.upsert_video_and_link(
        VideoCard(platform="bilibili", platform_video_id="BV1", url="u"), jid,
    )
    ok = ms.set_top_comments(vid, [
        {"text": "好用", "likes": 3, "author": "甲", "rank": 1, "extra": "dropped"},
        {"text": "x" * 600, "likes": None, "author": ""},
    ])
    assert ok

    rows, _ = ms.list_videos(commented="all")
    video = next(v for v in rows if v["id"] == vid)
    tc = video["top_comments"]
    assert tc[0] == {"text": "好用", "likes": 3, "author": "甲"}
    # 超长文本截 500；rank/extra 等字段不入快照
    assert len(tc[1]["text"]) == 500


def test_top_comments_null_when_unchecked(db):
    from csm_core.mining.models import VideoCard

    jid = ms.create_job("kw", ["bilibili"], 50)
    ms.upsert_video_and_link(
        VideoCard(platform="bilibili", platform_video_id="BV2", url="u"), jid,
    )
    rows, _ = ms.list_videos(commented="all")
    assert rows[0]["top_comments"] is None


# ---------------------------------------------------------------------------
# 模型层：StartJobRequest 默认值
# ---------------------------------------------------------------------------

def test_start_job_request_default_filters():
    from csm_core.mining.models import StartJobRequest

    req = StartJobRequest(keyword="kw")
    dumped = req.filters.model_dump()
    assert dumped["douyin"]["publish_time"] == "0"
    assert dumped["douyin"]["content_types"] == ["video"]
    assert dumped["bilibili"]["order"] == "totalrank"
    assert dumped["kuaishou"]["time_begin"] is None


def test_start_job_request_rejects_bad_enum():
    from pydantic import ValidationError

    from csm_core.mining.models import StartJobRequest

    with pytest.raises(ValidationError):
        StartJobRequest(keyword="kw", filters={"douyin": {"publish_time": "30"}})
