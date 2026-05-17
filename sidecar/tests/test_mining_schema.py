"""Verify v3 schema migration adds all mining tables on a fresh DB."""
import sqlite3
from pathlib import Path

import pytest

from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch):
    """Reset monitor_storage state and point it at a tmp_path DB."""
    # Reset module-level globals so init_db re-runs.
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    db = tmp_path / "monitor.db"
    monitor_storage.init_db(db)
    yield db
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)


def test_v3_creates_mining_tables(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r[0] for r in rows}
    assert "mining_jobs" in table_names
    assert "videos" in table_names
    assert "video_source_keywords" in table_names


def test_v3_videos_has_already_commented_columns(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    assert {"already_commented", "commented_source", "commented_at"} <= cols


def test_v3_videos_unique_platform_video_id(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','x','u')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','x','u2')"
        )


def test_v3_schema_version_recorded(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='version'"
    ).fetchone()
    assert row[0] == "3"
