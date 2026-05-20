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
