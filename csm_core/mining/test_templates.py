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
    # (Backfill may have populated rows from prior done comments, but
    # re-running must not double them.)
    n_before = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    mining_storage.apply_v5_migration(conn)
    n_after = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_after == n_before  # idempotent


def test_v5_indexes_exist(conn):
    idx = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='comment_templates'"
    ).fetchall()}
    assert "idx_templates_starred_last" in idx
    assert "idx_templates_hidden" in idx


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


# ── T3: backfill + update_comment hook ─────────────────────────────────


def test_backfill_inserts_existing_done_comments(tmp_path, monkeypatch):
    """Seed v4-style data, then trigger backfill, assert templates created."""
    db = tmp_path / "back.db"
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=False)
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=False)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=False)
    monitor_storage.init_db(str(db))
    conn = monitor_storage.get_conn()
    # Seed 3 done comments + 1 draft (draft should NOT be backfilled)
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'A', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 2, 'B', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 3, 'C', 'draft')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 4, 'A', 'done')")  # dup of 'A'
    # Wipe templates table to simulate "before backfill"
    conn.execute("DELETE FROM comment_templates")

    mining_storage._backfill_v5_templates(conn)

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 2  # 'A' + 'B' (C is draft, second 'A' deduped)
    uc = conn.execute("SELECT use_count FROM comment_templates WHERE text='A'").fetchone()[0]
    assert uc == 2  # 'A' got hit twice


def test_update_comment_draft_to_done_triggers_upsert(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '新评论', 'draft')")

    n_before = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_before == 0

    mining_storage.update_comment(1, status="done")

    n_after = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_after == 1
    row = conn.execute("SELECT text, source_platform FROM comment_templates").fetchone()
    assert row["text"] == "新评论"
    assert row["source_platform"] == "douyin"


def test_update_comment_status_unchanged_no_trigger(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'X', 'done')")
    conn.execute("DELETE FROM comment_templates")

    mining_storage.update_comment(1, text="X (edited)")  # status not changed (still 'done')

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 0  # no trigger — only draft→done triggers
