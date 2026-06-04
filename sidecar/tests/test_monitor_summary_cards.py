"""Tests for monitor_service.get_summary() — zhihu_search and geo_query cards.

These tests verify that the home-page summary returns the correct structure
for the two new platform types: zhihu_search (series.matched + prev) and
geo_query (series.soc + kpi_snapshot).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult
from csm_sidecar.services import monitor_service


def _seed_zhihu_search_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "zhihu_search",
        "name": "知乎搜索-扫地机器人",
        "target_url": "https://www.zhihu.com/search?q=扫地机器人哪个好",
        "config": {
            "search_keywords": ["扫地机器人哪个好"],
            "target_brand": "石头",
        },
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_geo_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "geo_query",
        "name": "GEO-扫地机器人",
        "target_url": "https://geo.example.com/brand/石头",
        "config": {
            "target_brand": "石头",
            "prompts": ["推荐扫地机器人"],
        },
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_zhihu_search_result(task_id: int, *, checked_at: datetime,
                               total_matches: int = 5,
                               best_first_rank: int = 2,
                               matched_keywords: int = 2):
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status="ok",
        rank=best_first_rank,
        metric={
            "total_matches": total_matches,
            "best_first_rank": best_first_rank,
            "matched_keywords": matched_keywords,
        },
        error_message="",
    ))


def _seed_geo_result(task_id: int, *, checked_at: datetime,
                     soc: float = 0.58,
                     sentiment_score: float = 0.3,
                     mentioned: int = 4):
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status="ok",
        rank=-1,
        metric={
            "soc": soc,
            "sentiment_score": sentiment_score,
            "mentioned": mentioned,
        },
        error_message="",
    ))


# ── zhihu_search card ──────────────────────────────────────────────────────

def test_zhihu_search_summary_card_structure(client: TestClient, monitor_db: Path):
    """zhihu_search 任务在 summary 里有 latest / prev / series。"""
    tid = _seed_zhihu_search_task(client)
    now = datetime.now()
    _seed_zhihu_search_result(tid, checked_at=now,
                               total_matches=5, best_first_rank=2, matched_keywords=2)

    s = monitor_service.get_summary()

    assert "zhihu_search" in s["platforms"], (
        "PLATFORM_TYPES must include 'zhihu_search'"
    )
    zs = s["platforms"]["zhihu_search"]
    assert zs["task_count"] == 1
    task_entry = zs["tasks"][0]
    assert task_entry["latest"] is not None
    assert "series" in task_entry
    assert len(task_entry["series"]) == 1
    # series entry has the 'matched' key (from total_matches)
    assert task_entry["series"][0]["matched"] == 5
    assert task_entry["series"][0]["checked_at"] is not None


def test_zhihu_search_summary_prev_populated(client: TestClient, monitor_db: Path):
    """两条结果时 prev 不为 None，series 按 oldest→newest 排列。"""
    from datetime import timedelta
    tid = _seed_zhihu_search_task(client)
    now = datetime.now()
    _seed_zhihu_search_result(tid, checked_at=now - timedelta(hours=1), total_matches=3)
    _seed_zhihu_search_result(tid, checked_at=now, total_matches=5)

    s = monitor_service.get_summary()
    task_entry = s["platforms"]["zhihu_search"]["tasks"][0]
    assert task_entry["prev"] is not None
    assert len(task_entry["series"]) == 2
    # oldest first → series[0].matched == 3
    assert task_entry["series"][0]["matched"] == 3
    assert task_entry["series"][1]["matched"] == 5


def test_zhihu_search_summary_empty_task(client: TestClient, monitor_db: Path):
    """没有结果时 latest=None，series=[]，不崩溃。"""
    _seed_zhihu_search_task(client)
    s = monitor_service.get_summary()
    task_entry = s["platforms"]["zhihu_search"]["tasks"][0]
    assert task_entry["latest"] is None
    assert task_entry["series"] == []


# ── geo_query card ─────────────────────────────────────────────────────────

def test_geo_summary_card_structure(client: TestClient, monitor_db: Path):
    """geo_query 任务在 summary 里有 latest / series / kpi_snapshot。"""
    tid = _seed_geo_task(client)
    now = datetime.now()
    _seed_geo_result(tid, checked_at=now, soc=0.58, sentiment_score=0.3, mentioned=4)

    s = monitor_service.get_summary()

    assert "geo_query" in s["platforms"]
    geo_platform = s["platforms"]["geo_query"]
    assert geo_platform["task_count"] == 1
    geo = geo_platform["tasks"][0]
    assert geo["latest"] is not None
    assert "series" in geo
    assert len(geo["series"]) == 1
    assert geo["series"][0]["soc"] == pytest.approx(0.58)
    assert geo["series"][0]["checked_at"] is not None

    assert "kpi_snapshot" in geo
    kpi = geo["kpi_snapshot"]
    assert kpi["soc"] == pytest.approx(0.58)
    assert kpi["sentiment"] == pytest.approx(0.3)
    assert kpi["mentioned"] == 4


def test_geo_summary_series_oldest_to_newest(client: TestClient, monitor_db: Path):
    """series 按 oldest→newest 排列，最后一条 soc 是最新值。"""
    from datetime import timedelta
    tid = _seed_geo_task(client)
    now = datetime.now()
    _seed_geo_result(tid, checked_at=now - timedelta(hours=2), soc=0.40)
    _seed_geo_result(tid, checked_at=now, soc=0.58)

    s = monitor_service.get_summary()
    geo = s["platforms"]["geo_query"]["tasks"][0]
    assert len(geo["series"]) == 2
    assert geo["series"][0]["soc"] == pytest.approx(0.40)
    assert geo["series"][-1]["soc"] == pytest.approx(0.58)


def test_geo_summary_empty_task(client: TestClient, monitor_db: Path):
    """没有结果时 latest=None，series=[]，kpi_snapshot 全零，不崩溃。"""
    _seed_geo_task(client)
    s = monitor_service.get_summary()
    geo = s["platforms"]["geo_query"]["tasks"][0]
    assert geo["latest"] is None
    assert geo["series"] == []
    assert geo["kpi_snapshot"] == {"soc": 0.0, "sentiment": 0.0, "mentioned": 0}


# ── Cross-platform assertions from the spec ───────────────────────────────

def test_summary_spec_assertions(client: TestClient, monitor_db: Path):
    """Spec 中的精确断言：zhihu_search task_count + series；geo kpi_snapshot.soc。"""
    zs_tid = _seed_zhihu_search_task(client)
    geo_tid = _seed_geo_task(client)
    now = datetime.now()

    _seed_zhihu_search_result(zs_tid, checked_at=now,
                               total_matches=5, best_first_rank=2, matched_keywords=2)
    _seed_geo_result(geo_tid, checked_at=now, soc=0.58, sentiment_score=0.3, mentioned=4)

    s = monitor_service.get_summary()
    zs = s["platforms"]["zhihu_search"]
    assert zs["task_count"] == 1
    assert zs["tasks"][0]["latest"] is not None
    assert "series" in zs["tasks"][0]

    geo = s["platforms"]["geo_query"]["tasks"][0]
    assert geo["kpi_snapshot"]["soc"] == pytest.approx(0.58)
    assert "series" in geo and geo["series"][-1]["soc"] == pytest.approx(0.58)
