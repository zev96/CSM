"""SQLite storage layer for the mining module.

Shares the monitor DB file (same ``init_db`` path). The 3 mining tables
are added in schema v3 — see ``_DDL_V3_MINING`` below; the actual
``ALTER`` / ``CREATE`` is run by ``csm_core.monitor.storage._migrate``
which knows the current version. Splitting the DDL list out here keeps
mining-specific concerns out of monitor/storage.py while still using
the same migration runner.

Connection model: re-uses ``monitor.storage.get_conn()`` — there is one
sqlite3.Connection per thread, WAL + foreign_keys on. Mining inserts
are autocommit (each ``on_card`` callback writes one row triple), no
explicit transactions needed; the runner already throttles cards to
≤1/200ms so WAL doesn't thrash.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from csm_core.monitor import storage as monitor_storage


# ── Schema v3 additions ─────────────────────────────────────────────────
_DDL_V3_MINING: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS mining_jobs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword             TEXT NOT NULL,
        platforms_json      TEXT NOT NULL,
        target_per_platform INTEGER NOT NULL DEFAULT 50,
        status              TEXT NOT NULL,
        progress_json       TEXT NOT NULL DEFAULT '{}',
        error_message       TEXT NOT NULL DEFAULT '',
        created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        started_at          TEXT,
        finished_at         TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_keyword ON mining_jobs(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_created ON mining_jobs(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS videos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        platform            TEXT NOT NULL,
        platform_video_id   TEXT NOT NULL,
        url                 TEXT NOT NULL,
        title               TEXT NOT NULL DEFAULT '',
        author_name         TEXT NOT NULL DEFAULT '',
        author_id           TEXT NOT NULL DEFAULT '',
        cover_url           TEXT NOT NULL DEFAULT '',
        duration_sec        INTEGER,
        play_count          INTEGER,
        like_count          INTEGER,
        published_at        TEXT,
        raw_json            TEXT NOT NULL DEFAULT '{}',
        excluded            INTEGER NOT NULL DEFAULT 0,
        already_commented   INTEGER NOT NULL DEFAULT 0,
        commented_source    TEXT,
        commented_at        TEXT,
        first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(platform, platform_video_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_videos_platform ON videos(platform)",
    "CREATE INDEX IF NOT EXISTS idx_videos_first_seen ON videos(first_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_videos_already_commented ON videos(already_commented, platform)",
    """
    CREATE TABLE IF NOT EXISTS video_source_keywords (
        video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        keyword         TEXT NOT NULL,
        job_id          INTEGER NOT NULL REFERENCES mining_jobs(id) ON DELETE CASCADE,
        rank_in_search  INTEGER NOT NULL,
        found_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY (video_id, keyword, job_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vsk_keyword ON video_source_keywords(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_vsk_job ON video_source_keywords(job_id)",
]


def apply_v3_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v2 → v3.

    Idempotent (all statements use IF NOT EXISTS).
    """
    for stmt in _DDL_V3_MINING:
        conn.execute(stmt)


def get_conn() -> sqlite3.Connection:
    """Thin alias — mining shares monitor's connection pool."""
    return monitor_storage.get_conn()
