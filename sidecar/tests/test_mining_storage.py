"""Direct unit tests for csm_core/mining/storage.py."""
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.mining.models import VideoCard
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    yield
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)


def _make_card(rank: int = 1, *, platform="douyin", vid="111") -> VideoCard:
    return VideoCard(
        platform=platform,
        platform_video_id=vid,
        url=f"https://example.com/video/{vid}",
        title=f"video {vid}",
        author_name="作者A",
        cover_url="http://x/cover.jpg",
        like_count=10,
        rank_in_search=rank,
    )


def test_create_job_returns_id(db):
    jid = ms.create_job("扫地机器人", ["douyin", "bilibili"], 50)
    assert jid > 0
    job = ms.get_job(jid)
    assert job["keyword"] == "扫地机器人"
    assert job["platforms"] == ["douyin", "bilibili"]
    assert job["status"] == "pending"


def test_upsert_video_inserts_and_links(db):
    jid = ms.create_job("k1", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(rank=3), jid)
    assert vid_id > 0
    rows, total = ms.list_videos(commented="all")
    assert total == 1
    assert rows[0]["source_keywords"] == ["k1"]


def test_upsert_video_dedups_on_second_call(db):
    j1 = ms.create_job("k1", ["douyin"], 50)
    j2 = ms.create_job("k2", ["douyin"], 50)
    id1 = ms.upsert_video_and_link(_make_card(), j1)
    id2 = ms.upsert_video_and_link(_make_card(), j2)
    assert id1 == id2  # same row
    rows, total = ms.list_videos(commented="all")
    assert total == 1  # single videos row
    assert set(rows[0]["source_keywords"]) == {"k1", "k2"}  # both keywords attached


def test_already_commented_marks_when_monitor_task_exists(db):
    # Pre-insert a monitor_task pointing at the same video.
    conn = monitor_storage.get_conn()
    conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron, last_check_at)
        VALUES('douyin_comment', 'my_comment', 'https://www.douyin.com/video/111', '{}', 'manual', '2026-05-10T00:00:00Z')
        """
    )
    jid = ms.create_job("k1", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(vid="111"), jid)
    rows, _ = ms.list_videos(commented="1")
    assert len(rows) == 1
    assert rows[0]["id"] == vid_id
    assert rows[0]["already_commented"] is True
    assert rows[0]["commented_source"] == "monitor_task"


def test_already_commented_does_not_mark_unrelated(db):
    conn = monitor_storage.get_conn()
    conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron)
        VALUES('douyin_comment', 'other', 'https://www.douyin.com/video/999', '{}', 'manual')
        """
    )
    jid = ms.create_job("k1", ["douyin"], 50)
    ms.upsert_video_and_link(_make_card(vid="111"), jid)
    rows, _ = ms.list_videos(commented="0")
    assert len(rows) == 1
    assert rows[0]["already_commented"] is False


def test_already_commented_uses_short_url_pattern(db):
    """modal_id form must also match the same platform_video_id."""
    conn = monitor_storage.get_conn()
    conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron)
        VALUES('douyin_comment', 'modal', 'https://www.douyin.com/discover?modal_id=111', '{}', 'manual')
        """
    )
    jid = ms.create_job("k1", ["douyin"], 50)
    ms.upsert_video_and_link(_make_card(vid="111"), jid)
    rows, _ = ms.list_videos(commented="1")
    assert len(rows) == 1


def test_list_videos_filter_by_commented(db):
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron) "
        "VALUES('douyin_comment','m','https://www.douyin.com/video/111','{}','manual')"
    )
    jid = ms.create_job("k", ["douyin"], 50)
    ms.upsert_video_and_link(_make_card(vid="111"), jid)
    ms.upsert_video_and_link(_make_card(vid="222"), jid)
    uncommented, _ = ms.list_videos(commented="0")
    commented, _ = ms.list_videos(commented="1")
    all_videos, _ = ms.list_videos(commented="all")
    assert len(uncommented) == 1
    assert len(commented) == 1
    assert len(all_videos) == 2


def test_soft_delete_excludes_from_list(db):
    jid = ms.create_job("k", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(), jid)
    assert ms.soft_delete_video(vid_id) is True
    rows, total = ms.list_videos(commented="all")
    assert total == 0


def test_finalize_job_done_when_all_platforms_done(db):
    jid = ms.create_job("k", ["douyin", "bilibili"], 50)
    ms.update_platform_progress(jid, "douyin", got=50, target=50, phase="done")
    ms.update_platform_progress(jid, "bilibili", got=50, target=50, phase="done")
    summary = ms.finalize_job(jid)
    assert summary["status"] == "done"


def test_finalize_job_partial_when_mixed(db):
    jid = ms.create_job("k", ["douyin", "bilibili"], 50)
    ms.update_platform_progress(jid, "douyin", got=0, target=50, phase="needs_login")
    ms.update_platform_progress(jid, "bilibili", got=50, target=50, phase="done")
    summary = ms.finalize_job(jid)
    assert summary["status"] == "partial_done"


def test_cancel_running_job_flips_status(db):
    jid = ms.create_job("k", ["douyin"], 50)
    ms.mark_started(jid)
    assert ms.cancel_job_if_running(jid) is True
    assert ms.get_job(jid)["status"] == "cancelled"


def test_finalize_job_preserves_cancelled_status(db):
    jid = ms.create_job("k", ["douyin"], 50)
    ms.mark_started(jid)
    assert ms.cancel_job_if_running(jid) is True
    # Simulate runner finishing after cancel.
    ms.update_platform_progress(jid, "douyin", got=3, target=50, phase="cancelled")
    summary = ms.finalize_job(jid)
    assert summary["status"] == "cancelled"
    job = ms.get_job(jid)
    assert job["status"] == "cancelled"
    assert job["finished_at"] is not None


def test_extract_platform_video_id_handles_short_forms():
    assert ms.extract_platform_video_id("douyin", "https://www.douyin.com/video/7123") == "7123"
    assert ms.extract_platform_video_id("douyin", "https://www.douyin.com/?modal_id=7123") == "7123"
    assert ms.extract_platform_video_id("bilibili", "https://b23.tv/video/BV1ab2cd3ef4") == "BV1ab2cd3ef4"
    assert ms.extract_platform_video_id("kuaishou", "https://www.kuaishou.com/short-video/aZ9Q1xY") == "aZ9Q1xY"
    assert ms.extract_platform_video_id("douyin", "https://example.com") is None


def test_mining_browser_import_only():
    from csm_core.browser_infra import mining_browser
    assert callable(mining_browser.launched_page)
    assert callable(mining_browser.has_login_cookie)


# ── V8 migration: brand pre-filter columns ───────────────────────────────

def test_v8_migration_columns_exist(db):
    """videos gets brand_comment_hits + exclude_reason; mining_jobs gets brand_keywords_json."""
    conn = monitor_storage.get_conn()

    videos_cols = {row[1] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    assert "brand_comment_hits" in videos_cols, "videos.brand_comment_hits missing"
    assert "exclude_reason" in videos_cols, "videos.exclude_reason missing"

    jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(mining_jobs)").fetchall()}
    assert "brand_keywords_json" in jobs_cols, "mining_jobs.brand_keywords_json missing"


def test_mark_brand_excluded_sets_fields(db):
    """mark_brand_excluded sets excluded=1, exclude_reason='brand_seeded', brand_comment_hits."""
    jid = ms.create_job("扫地机器人", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(), jid)

    result = ms.mark_brand_excluded(vid_id, hits=4)
    assert result is True

    # list_videos filters excluded=0, so query directly.
    conn = monitor_storage.get_conn()
    row = conn.execute(
        "SELECT excluded, exclude_reason, brand_comment_hits FROM videos WHERE id=?",
        (vid_id,),
    ).fetchone()
    assert row["excluded"] == 1
    assert row["exclude_reason"] == "brand_seeded"
    assert row["brand_comment_hits"] == 4


def test_mark_brand_excluded_unknown_id_returns_false(db):
    assert ms.mark_brand_excluded(999999, hits=1) is False


def test_create_job_with_brand_keywords(db):
    """create_job accepts brand_keywords; get_job surfaces them via brand_keywords key."""
    jid = ms.create_job("扫地机器人", ["douyin"], 50, brand_keywords=["石头", "roborock"])
    job = ms.get_job(jid)
    assert job["brand_keywords"] == ["石头", "roborock"]


def test_create_job_default_brand_keywords_empty(db):
    """create_job without brand_keywords → brand_keywords=[] in get_job."""
    jid = ms.create_job("k", ["douyin"], 50)
    job = ms.get_job(jid)
    assert job["brand_keywords"] == []


def test_set_brand_hits_updates_without_excluding(db):
    """set_brand_hits records hits but does NOT flip excluded."""
    jid = ms.create_job("k", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(), jid)

    ms.set_brand_hits(vid_id, hits=2)

    conn = monitor_storage.get_conn()
    row = conn.execute(
        "SELECT excluded, brand_comment_hits FROM videos WHERE id=?",
        (vid_id,),
    ).fetchone()
    assert row["excluded"] == 0      # NOT excluded
    assert row["brand_comment_hits"] == 2


def test_row_to_video_dict_surfaces_brand_fields(db):
    """_row_to_video_dict (via list_videos include_excluded) exposes brand_comment_hits + exclude_reason."""
    jid = ms.create_job("k", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(), jid)
    ms.mark_brand_excluded(vid_id, hits=7)

    # Use the conn directly to bypass excluded=0 filter in list_videos.
    conn = monitor_storage.get_conn()
    row = conn.execute(
        """
        SELECT v.*, GROUP_CONCAT(sk.keyword) AS source_keywords
        FROM videos v
        LEFT JOIN video_source_keywords sk ON sk.video_id = v.id
        WHERE v.id=?
        GROUP BY v.id
        """,
        (vid_id,),
    ).fetchone()
    d = ms._row_to_video_dict(row)
    assert d["brand_comment_hits"] == 7
    assert d["exclude_reason"] == "brand_seeded"
