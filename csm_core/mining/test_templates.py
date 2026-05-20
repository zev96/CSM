"""Schema v5 migration test — comment_templates table.

T1 of the comment-template-library plan. Three concerns:
  1. Fresh DB v0 → v5 creates the comment_templates table with the
     expected columns.
  2. apply_v5_migration is idempotent (CREATE ... IF NOT EXISTS).
  3. The two expected indexes (starred_last, hidden) exist.

The conn fixture resets monitor_storage module globals via monkeypatch
so each test gets a clean per-tmp_path DB (same pattern as
sidecar/tests/test_mining_storage_v4.py).
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from csm_core.monitor import storage as monitor_storage
from csm_core.mining import storage as mining_storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    # Reset module-level singletons so each test gets a fresh DB; without
    # this, the second test would hit the "already initialized" guard.
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(str(db))
    return monitor_storage.get_conn()


def test_v5_creates_templates_table(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comment_templates)").fetchall()}
    assert {
        "id", "text", "text_hash", "tags_json", "source_platform",
        "source_comment_id", "starred", "hidden", "use_count",
        "first_seen_at", "last_used_at",
    } <= cols


def test_v5_migration_idempotent(conn):
    # Re-run apply_v5_migration on already-migrated DB — should not raise.
    mining_storage.apply_v5_migration(conn)
    mining_storage.apply_v5_migration(conn)
    # Table still has zero rows
    assert conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0] == 0


def test_v5_indexes_exist(conn):
    idx = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='comment_templates'"
    ).fetchall()}
    assert "idx_templates_starred_last" in idx
    assert "idx_templates_hidden" in idx


import json
from csm_core.mining.storage import (
    _normalize_text, _hash_text, _upsert_template_from_comment,
)


def test_normalize_strips_and_lowers():
    assert _normalize_text("  Hello World  ") == "hello world"
    assert _normalize_text("很赞！") == "很赞！"  # 中文 + 标点保留
    assert _normalize_text("test\n") == "test"


def test_hash_is_deterministic():
    assert _hash_text("hello") == _hash_text("HELLO")
    assert _hash_text("hello") == _hash_text("  hello  ")
    assert _hash_text("hello") != _hash_text("hello!")


def test_upsert_inserts_new_template(conn):
    # Create a video + comment so source_comment_id is valid
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','vid1','http://x')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '吸力够大', 'done')")
    comment_row = dict(conn.execute(
        "SELECT id, video_id, text FROM video_comments WHERE id=1"
    ).fetchone())

    _upsert_template_from_comment(conn, comment_row)

    row = conn.execute("SELECT text, text_hash, source_platform, source_comment_id, use_count FROM comment_templates").fetchone()
    assert row["text"] == "吸力够大"
    assert row["text_hash"] == _hash_text("吸力够大")
    assert row["source_platform"] == "kuaishou"
    assert row["source_comment_id"] == 1
    assert row["use_count"] == 1


def test_upsert_second_time_bumps_use_count(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','vid1','http://x')")
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','vid2','http://y')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '吸力够大', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(2, 1, '吸力够大', 'done')")
    c1 = dict(conn.execute("SELECT id, video_id, text FROM video_comments WHERE id=1").fetchone())
    c2 = dict(conn.execute("SELECT id, video_id, text FROM video_comments WHERE id=2").fetchone())

    _upsert_template_from_comment(conn, c1)
    _upsert_template_from_comment(conn, c2)

    rows = conn.execute("SELECT COUNT(*), MAX(use_count), MIN(source_comment_id) FROM comment_templates").fetchone()
    assert rows[0] == 1                  # only 1 row (dedup)
    assert rows[1] == 2                  # use_count bumped
    assert rows[2] == 1                  # source_comment_id stays at first
