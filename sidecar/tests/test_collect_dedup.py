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
    monitor_storage._local.conn = None  # explicit eviction before monkeypatch undo


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


def _create_monitor_task(conn, type_, target_url, my_text="x"):
    """Helper to insert a monitor task directly."""
    import json
    conn.execute(
        "INSERT INTO monitor_tasks(type, name, target_url, config_json, enabled) "
        "VALUES (?, ?, ?, ?, ?)",
        (type_, "test", target_url, json.dumps({"my_comment_text": my_text, "top_n": 5}), 0),
    )


def test_is_video_in_monitor_tasks_when_present(temp_db):
    conn = temp_db
    _create_monitor_task(
        conn, "douyin_comment",
        "https://www.douyin.com/video/7000000000001"
    )
    assert mining_storage.is_video_in_monitor_tasks(conn, "douyin", "7000000000001") is True


def test_is_video_in_monitor_tasks_when_absent(temp_db):
    assert mining_storage.is_video_in_monitor_tasks(temp_db, "douyin", "9999999999") is False


def test_is_video_in_monitor_tasks_wrong_type_not_matched(temp_db):
    """zhihu_question 类型 task 包含相同 id 子串不应误判为 douyin 命中。"""
    conn = temp_db
    _create_monitor_task(
        conn, "zhihu_question",
        "https://zhihu.com/q/7000000000001",
    )
    assert mining_storage.is_video_in_monitor_tasks(conn, "douyin", "7000000000001") is False


def test_is_video_in_monitor_tasks_unknown_platform(temp_db):
    """未知 platform 直接返回 False，不查 monitor。"""
    assert mining_storage.is_video_in_monitor_tasks(temp_db, "weibo", "7000000000001") is False
