"""Tests for /api/monitor/history/* — comment retention + zhihu ranking aggregation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult


def _seed_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "bilibili_comment",
        "name": "0514 - BV001",
        "target_url": "https://www.bilibili.com/video/BV001",
        "config": {"my_comment_text": "test", "top_n": 5},
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_result(task_id: int, *, checked_at: datetime, matched: bool, status: str = "ok",
                 hot_comments=None, my_comment_text: str = "test"):
    """Insert a MonitorResult row directly via storage (bypassing the HTTP layer)."""
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status=status,
        rank=1 if matched else -1,
        metric={
            "matched": matched,
            "my_comment_text": my_comment_text,
            "total_fetched": 17 if matched else 0,
            "scope_total": 17 if matched else 0,
            "hot_comments": hot_comments or [],
            "scrape_top_n": 150,
            "alert_top_n": 5,
        },
        error_message="",
    ))


def test_comment_retention_empty_db_returns_zero_platforms(client: TestClient, monitor_db: Path):
    """空 DB 时三个平台都返回 0/0，不挂。"""
    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "7d"
    assert set(body["platforms"].keys()) == {"bilibili_comment", "douyin_comment", "kuaishou_comment"}
    for p in body["platforms"].values():
        assert p["current_total"] == 0
        assert p["current_retained"] == 0
        assert len(p["daily_series"]) == 7
        assert all(d["total"] == 0 for d in p["daily_series"])
    assert body["events"] == []


def test_comment_retention_groups_by_day_and_dedups_same_task(client: TestClient, monitor_db: Path):
    """同一 task 同一天有两次 result，取最新那次。"""
    tid = _seed_task(client, type="bilibili_comment", name="0514 - BV001")
    now = datetime.now()
    # 早上跑了一次 matched=True
    _seed_result(tid, checked_at=now.replace(hour=9, minute=0, second=0), matched=True)
    # 下午跑了一次 matched=False（这次应胜出）
    _seed_result(tid, checked_at=now.replace(hour=15, minute=0, second=0), matched=False)

    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    body = resp.json()
    bili = body["platforms"]["bilibili_comment"]
    assert bili["current_total"] == 1
    assert bili["current_retained"] == 0  # 下午那次 matched=False 胜出
    assert bili["current_deleted"] == 1
    # daily_series 应有 7 天，最后一天是今天
    assert len(bili["daily_series"]) == 7
    today = now.strftime("%Y-%m-%d")
    last = bili["daily_series"][-1]
    assert last["date"] == today
    assert last["total"] == 1 and last["retained"] == 0


def test_comment_retention_rate_prev_uses_range_days_offset(client: TestClient, monitor_db: Path):
    """rate_prev 取 N 日前同形态的快照。7d range → 7 天前；1d range → 昨天。"""
    tid = _seed_task(client, type="douyin_comment", name="A - vid1")
    now = datetime.now()
    # 7 天前 matched=True，今天 matched=False → rate 从 1.0 → 0.0
    _seed_result(tid, checked_at=now - timedelta(days=7), matched=True)
    _seed_result(tid, checked_at=now, matched=False)

    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    douyin = resp.json()["platforms"]["douyin_comment"]
    assert douyin["rate_today"] == 0.0
    assert douyin["rate_prev"] == 1.0


def test_comment_retention_events_surface_unmatched_rows(client: TestClient, monitor_db: Path):
    """matched=False 的最新 result 进 events 列表。"""
    tid = _seed_task(client, type="kuaishou_comment", name="0514 - X-7Ellfy")
    now = datetime.now()
    _seed_result(tid, checked_at=now - timedelta(hours=2), matched=False,
                 my_comment_text="抽烟可以，但麻烦避开人群")
    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    events = resp.json()["events"]
    assert len(events) == 1
    e = events[0]
    assert e["platform"] == "kuaishou_comment"
    assert e["task_id"] == tid
    assert e["batch_name"] == "0514"
    assert e["video_title"] == "X-7Ellfy"
    assert "抽烟可以" in e["comment_text"]
    assert e["status"] == "deleted"


def test_comment_retention_invalid_range_400(client: TestClient, monitor_db: Path):
    resp = client.get("/api/monitor/history/comment-retention?range=2d")
    assert resp.status_code == 400
    assert "range" in resp.json()["detail"]
