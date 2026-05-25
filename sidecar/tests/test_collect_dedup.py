"""Tests for cross-table dedup helpers used by mining collection."""
from __future__ import annotations

import threading

import pytest

from csm_core.mining import storage as mining_storage
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Each test gets a fresh SQLite file with both monitor + mining schema."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(db_path)
    conn = monitor_storage.get_conn()
    yield conn
    conn.close()


def test_is_video_in_videos_table_when_present(temp_db):
    conn = temp_db
    # Insert one video directly
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) "
        "VALUES (?, ?, ?, ?)",
        ("douyin", "7000000000001", "https://www.douyin.com/video/7000000000001", "x"),
    )
    assert mining_storage.is_video_in_videos_table(conn, "douyin", "7000000000001") is True


def test_is_video_in_videos_table_when_absent(temp_db):
    assert mining_storage.is_video_in_videos_table(temp_db, "douyin", "9999999999") is False


def test_is_video_in_videos_table_different_platform_same_id(temp_db):
    conn = temp_db
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) "
        "VALUES (?, ?, ?, ?)",
        ("douyin", "7000000000001", "https://www.douyin.com/video/7000000000001", "x"),
    )
    # 同 id 不同平台不应误判
    assert mining_storage.is_video_in_videos_table(conn, "kuaishou", "7000000000001") is False
