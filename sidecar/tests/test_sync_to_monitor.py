"""Tests for mining → monitor sync service."""
from __future__ import annotations

import json
import threading

import pytest

from csm_core.mining import storage as mining_storage
from csm_core.mining import sync_to_monitor
from csm_core.mining.sync_to_monitor import SyncParams, SyncResult
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db_with_job(tmp_path, monkeypatch):
    """Fresh DB with one mining job + 5 videos."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(db_path)
    conn = monitor_storage.get_conn()

    # Create job
    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("test_kw", json.dumps(["douyin"]), 5, "done"),
    ).fetchone()[0]

    # Create 5 videos with already_commented=1
    for vid in ["v1", "v2", "v3", "v4", "v5"]:
        video_id = conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
            "VALUES (?, ?, ?, ?, 1) RETURNING id",
            ("douyin", vid, f"https://www.douyin.com/video/{vid}", f"title-{vid}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
            "VALUES (?, ?, ?, ?)",
            (video_id, job_id, "test_kw", 0),
        )
        # Add tier=1 comment for first 3 videos only
        if vid in ("v1", "v2", "v3"):
            conn.execute(
                "INSERT INTO video_comments(video_id, tier, text, status, source) "
                "VALUES (?, 1, ?, 'draft', 'manual')",
                (video_id, f"comment for {vid}"),
            )

    yield conn, job_id
    conn.close()
    monitor_storage._local.conn = None  # explicit eviction before monkeypatch undo


def test_sync_creates_monitor_tasks(db_with_job):
    conn, job_id = db_with_job
    result = sync_to_monitor.run(
        conn, job_id,
        SyncParams(task_name_prefix="batch-1", top_n=5),
    )
    assert isinstance(result, SyncResult)
    assert result.created == 3  # only v1/v2/v3 have tier=1 drafts
    assert result.skipped_no_draft == 2  # v4, v5
    assert result.skipped_dup == 0
    assert result.errors == []

    # Verify in DB
    rows = conn.execute(
        "SELECT type, name, target_url, config_json, enabled FROM monitor_tasks ORDER BY id"
    ).fetchall()
    assert len(rows) == 3
    for row in rows:
        assert row[0] == "douyin_comment"
        assert row[1].startswith("batch-1 - ")
        assert row[4] == 0  # enabled=False
        cfg = json.loads(row[3])
        assert "my_comment_text" in cfg
        assert cfg["top_n"] == 5
        assert cfg["scrape_top_n"] == 150
