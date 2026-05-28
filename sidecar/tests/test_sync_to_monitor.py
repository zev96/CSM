"""Tests for mining → monitor sync service."""
from __future__ import annotations

import json
import sqlite3
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


@pytest.fixture
def db_with_job_numeric(tmp_path, monkeypatch):
    """Fresh DB with one mining job + 5 douyin videos using realistic numeric IDs.

    Uses IDs 7000000000001–7000000000005 so that extract_platform_video_id()
    (which requires \\d+) can correctly identify them during dup checks.
    """
    db_path = tmp_path / "test_numeric.db"
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(db_path)
    conn = monitor_storage.get_conn()

    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw2", json.dumps(["douyin"]), 5, "done"),
    ).fetchone()[0]

    numeric_ids = [
        "7000000000001",
        "7000000000002",
        "7000000000003",
        "7000000000004",
        "7000000000005",
    ]
    for vid in numeric_ids:
        video_id = conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
            "VALUES (?, ?, ?, ?, 1) RETURNING id",
            ("douyin", vid, f"https://www.douyin.com/video/{vid}", f"title-{vid}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
            "VALUES (?, ?, ?, ?)",
            (video_id, job_id, "kw2", 0),
        )
        # Add tier=1 comment for first 3 videos only
        if vid in ("7000000000001", "7000000000002", "7000000000003"):
            conn.execute(
                "INSERT INTO video_comments(video_id, tier, text, status, source) "
                "VALUES (?, 1, ?, 'draft', 'manual')",
                (video_id, f"comment for {vid}"),
            )

    yield conn, job_id
    conn.close()
    monitor_storage._local.conn = None


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


def test_sync_skips_soft_deleted_videos(db_with_job):
    """Soft-deleted (excluded=1) videos are not synced at all.

    v1 has a tier=1 draft but is excluded → must drop out of the query, so
    created counts only v2/v3 and no monitor_task is made for v1.
    """
    conn, job_id = db_with_job
    conn.execute("UPDATE videos SET excluded=1 WHERE platform_video_id='v1'")

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="x", top_n=5)
    )
    assert result.created == 2  # v2, v3 (v1 excluded out entirely)
    assert result.skipped_no_draft == 2  # v4, v5 still counted, no draft

    urls = [r[0] for r in conn.execute(
        "SELECT target_url FROM monitor_tasks"
    ).fetchall()]
    assert not any("/v1" in u for u in urls)


def test_sync_skips_dup_in_monitor_tasks(db_with_job_numeric):
    conn, job_id = db_with_job_numeric
    # Pre-insert a monitor_task for 7000000000001 (the first numeric video)
    conn.execute(
        "INSERT INTO monitor_tasks(type, name, target_url, config_json, enabled) "
        "VALUES ('douyin_comment', 'pre-existing', "
        "'https://www.douyin.com/video/7000000000001', '{}', 0)",
    )

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="batch", top_n=5)
    )
    assert result.skipped_dup == 1  # 7000000000001
    assert result.created == 2  # 7000000000002, 7000000000003
    assert result.skipped_no_draft == 2  # 7000000000004, 7000000000005


def test_sync_empty_text_treated_as_no_draft(db_with_job):
    conn, job_id = db_with_job
    # Clear v1's text to empty string
    conn.execute("UPDATE video_comments SET text='' WHERE text LIKE 'comment for v1'")

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="batch", top_n=5)
    )
    assert result.created == 2  # v2, v3 only
    assert result.skipped_no_draft == 3  # v1 (empty), v4, v5


def test_sync_whitespace_only_text_is_no_draft(db_with_job):
    conn, job_id = db_with_job
    conn.execute("UPDATE video_comments SET text='   \n  ' WHERE text LIKE 'comment for v2'")

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="batch", top_n=5)
    )
    assert result.skipped_no_draft >= 1  # at least v2 stripped to empty


def test_sync_repeat_idempotent(db_with_job_numeric):
    """Running sync twice in a row: second run all dup.

    Uses numeric douyin IDs so extract_platform_video_id() can resolve them
    and is_video_in_monitor_tasks() correctly returns True on the second pass.
    """
    conn, job_id = db_with_job_numeric
    first = sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="x", top_n=5))
    assert first.created == 3

    second = sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="x", top_n=5))
    assert second.created == 0
    assert second.skipped_dup == 3
    assert second.skipped_no_draft == 2


def test_sync_single_failure_does_not_break_batch(db_with_job):
    """Force one INSERT to fail; others succeed; errors[] has the failure.

    sqlite3.Connection.execute is a read-only C attribute so we can't
    monkeypatch it directly.  Instead we wrap the connection in a thin proxy
    whose .execute is a plain Python method that we can make flaky.
    """
    conn, job_id = db_with_job

    call_count = {"n": 0}

    class FlakyConnProxy:
        """Thin proxy that delegates everything to the real connection but
        raises sqlite3.OperationalError on the second INSERT INTO monitor_tasks."""

        def __init__(self, real_conn):
            self._conn = real_conn

        def execute(self, sql, *args, **kwargs):
            if "INSERT INTO monitor_tasks" in sql:
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise sqlite3.OperationalError("simulated fault")
            return self._conn.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    proxy = FlakyConnProxy(conn)
    result = sync_to_monitor.run(proxy, job_id, SyncParams(task_name_prefix="b", top_n=5))
    assert result.created == 2
    assert len(result.errors) == 1
    assert "simulated fault" in result.errors[0]["reason"]


def test_sync_platform_mapping(tmp_path, monkeypatch):
    """kuaishou + bilibili platforms map to correct task types."""
    db_path = tmp_path / "test2.db"
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(db_path)
    conn = monitor_storage.get_conn()

    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw", json.dumps(["kuaishou", "bilibili"]), 5, "done"),
    ).fetchone()[0]

    for platform, vid, url in [
        ("kuaishou", "k1", "https://www.kuaishou.com/short-video/k1"),
        ("bilibili", "BV1a2b3c4", "https://www.bilibili.com/video/BV1a2b3c4"),
    ]:
        video_id = conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
            "VALUES (?, ?, ?, ?, 1) RETURNING id",
            (platform, vid, url, vid),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
            "VALUES (?, ?, ?, ?)",
            (video_id, job_id, "kw", 0),
        )
        conn.execute(
            "INSERT INTO video_comments(video_id, tier, text, status, source) "
            "VALUES (?, 1, ?, 'draft', 'manual')",
            (video_id, "x"),
        )

    sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="m", top_n=5))
    types = conn.execute("SELECT type FROM monitor_tasks ORDER BY id").fetchall()
    assert [t[0] for t in types] == ["kuaishou_comment", "bilibili_comment"]

    conn.close()
    monitor_storage._local.conn = None
