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


# ── Zhihu ranking helpers ──────────────────────────────────────────────────

def _seed_zhihu_result(task_id: int, *, checked_at: datetime, matched_count: int,
                       best_rank: int = -1, top_n: int = 10):
    """Insert a zhihu MonitorResult."""
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status="ok",
        rank=best_rank if matched_count > 0 else -1,
        metric={
            "matched_count": matched_count,
            "matched_ranks": list(range(1, matched_count + 1)),  # 简化，rank=1..N
            "top_n": top_n,
            "alert_top_n": 5,
            "target_brand": "拾梧",
        },
        error_message="",
    ))


def test_zhihu_change_kind_down_when_match_count_drops(client: TestClient, monitor_db: Path):
    """matched_count 减少 → change_kind=down。"""
    tid = _seed_task(client, type="zhihu_question", name="Q1",
                     target_url="https://www.zhihu.com/question/1",
                     config={"target_brand": "拾梧", "top_n": 10})
    now = datetime.now()
    _seed_zhihu_result(tid, checked_at=now - timedelta(hours=2), matched_count=5)
    _seed_zhihu_result(tid, checked_at=now, matched_count=3)
    resp = client.get("/api/monitor/history/zhihu-ranking?range=7d")
    assert resp.status_code == 200
    q = next(q for q in resp.json()["questions"] if q["task_id"] == tid)
    assert q["change_kind"] == "down"
    assert q["matched_count"] == 3
    assert q["matched_count_prev"] == 5


def test_zhihu_change_kind_dropped_when_all_hits_gone(client: TestClient, monitor_db: Path):
    """有命中 → 无命中 → dropped。"""
    tid = _seed_task(client, type="zhihu_question", name="Q2",
                     target_url="https://www.zhihu.com/question/2",
                     config={"target_brand": "拾梧", "top_n": 10})
    now = datetime.now()
    _seed_zhihu_result(tid, checked_at=now - timedelta(hours=2), matched_count=2)
    _seed_zhihu_result(tid, checked_at=now, matched_count=0)
    q = next(q for q in client.get("/api/monitor/history/zhihu-ranking?range=7d").json()["questions"]
             if q["task_id"] == tid)
    assert q["change_kind"] == "dropped"


def test_zhihu_change_kind_new_when_first_hit(client: TestClient, monitor_db: Path):
    """无命中 → 有命中 → new。"""
    tid = _seed_task(client, type="zhihu_question", name="Q3",
                     target_url="https://www.zhihu.com/question/3",
                     config={"target_brand": "拾梧", "top_n": 10})
    now = datetime.now()
    _seed_zhihu_result(tid, checked_at=now - timedelta(hours=2), matched_count=0)
    _seed_zhihu_result(tid, checked_at=now, matched_count=2)
    q = next(q for q in client.get("/api/monitor/history/zhihu-ranking?range=7d").json()["questions"]
             if q["task_id"] == tid)
    assert q["change_kind"] == "new"


def test_zhihu_change_kind_flat_first_time_seen(client: TestClient, monitor_db: Path):
    """只跑过一次（prev 不存在）→ flat。"""
    tid = _seed_task(client, type="zhihu_question", name="Q4",
                     target_url="https://www.zhihu.com/question/4",
                     config={"target_brand": "拾梧", "top_n": 10})
    _seed_zhihu_result(tid, checked_at=datetime.now(), matched_count=3)
    q = next(q for q in client.get("/api/monitor/history/zhihu-ranking?range=7d").json()["questions"]
             if q["task_id"] == tid)
    assert q["change_kind"] == "flat"


def test_zhihu_kpis_aggregate_across_questions(client: TestClient, monitor_db: Path):
    """跨多个问题聚合：avg_share = ∑matched / ∑top_n，changed_count 统计。"""
    now = datetime.now()
    # Q1: 5/10 命中（旧）→ 3/10（新） — down
    t1 = _seed_task(client, type="zhihu_question", name="Q1",
                    target_url="https://www.zhihu.com/question/1",
                    config={"target_brand": "拾梧", "top_n": 10})
    _seed_zhihu_result(t1, checked_at=now - timedelta(hours=2), matched_count=5)
    _seed_zhihu_result(t1, checked_at=now, matched_count=3)
    # Q2: 0/10 → 2/10 — new (新上榜也算 up 类)
    t2 = _seed_task(client, type="zhihu_question", name="Q2",
                    target_url="https://www.zhihu.com/question/2",
                    config={"target_brand": "拾梧", "top_n": 10})
    _seed_zhihu_result(t2, checked_at=now - timedelta(hours=2), matched_count=0)
    _seed_zhihu_result(t2, checked_at=now, matched_count=2)

    body = client.get("/api/monitor/history/zhihu-ranking?range=7d").json()
    k = body["kpis"]
    assert k["monitored_questions"] == 2
    # avg_share_today = (3+2) / (10+10) = 0.25
    assert k["avg_share_today"] == pytest.approx(0.25)
    # changed_questions = 2 (Q1 down + Q2 new)
    assert k["changed_questions"] == 2
    assert k["changed_down"] == 1
    assert k["changed_up"] == 1  # "new" 也算 up 类（新增命中）


# ── Baidu keyword history ──────────────────────────────────────────────────

def _seed_baidu_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "baidu_keyword",
        "name": "测试关键词",
        "target_url": "https://www.baidu.com/s?wd=kw1",
        "config": {
            "search_keywords": ["kw1"],
            "target_brand": "拾梧",
        },
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_baidu_result(
    task_id: int,
    *,
    checked_at: datetime,
    matched_count: int,
    best_rank: int = -1,
    captcha_hit: bool = False,
    news_present: bool = False,
    keyword: str = "kw1",
):
    """Insert a baidu_keyword MonitorResult with the new metric shape."""
    default_results = []
    for i in range(1, 11):
        default_results.append({
            "rank": i,
            "matches_brand": i <= matched_count,
        })
    kw_entry = {
        "keyword": keyword,
        "serp_url": f"https://www.baidu.com/s?wd={keyword}",
        "default_results": default_results,
        "news_results": [],
        "default_matched_count": matched_count,
        "default_first_rank": best_rank,
        "news_first_rank": -1,
        "news_present": news_present,
        "fetch_error": None,
    }
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status="ok",
        rank=best_rank if matched_count > 0 else -1,
        metric={
            "target_brand": "拾梧",
            "search_keywords": [keyword],
            "engine": "patchright",
            "headless": True,
            "captcha_hit": captcha_hit,
            "keywords": [kw_entry],
            "total_keywords": 1,
            "matched_keywords": 1 if matched_count > 0 else 0,
            "total_default_matches": matched_count,
            "best_default_first_rank": best_rank,
        },
        error_message="",
    ))


def test_baidu_keyword_history_empty_db(client: TestClient, monitor_db: Path):
    """空 DB 返回 200，monitored_keywords=0，keywords=[]。"""
    resp = client.get("/api/monitor/history/baidu-keyword?range=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "7d"
    assert body["kpis"]["monitored_keywords"] == 0
    assert body["keywords"] == []
    assert len(body["daily_series"]) == 7
    assert all(d["avg_match_rate"] == 0.0 for d in body["daily_series"])


def test_baidu_keyword_history_change_kind_new(client: TestClient, monitor_db: Path):
    """无命中 → 有命中 → change_kind=new。"""
    tid = _seed_baidu_task(
        client,
        config={"search_keywords": ["kw1"], "target_brand": "BrandA"},
        target_url="https://www.baidu.com/s?wd=kw1",
    )
    now = datetime.now()
    _seed_baidu_result(tid, checked_at=now - timedelta(hours=2), matched_count=0, keyword="kw1")
    _seed_baidu_result(tid, checked_at=now, matched_count=3, best_rank=2, keyword="kw1")
    resp = client.get("/api/monitor/history/baidu-keyword?range=7d")
    assert resp.status_code == 200
    body = resp.json()
    # One row per (task, keyword) — task has 1 keyword → 1 row
    kw = next(k for k in body["keywords"] if k["task_id"] == tid)
    assert kw["change_kind"] == "new"
    assert kw["matched_count"] == 3
    assert kw["best_rank"] == 2
    assert kw["search_keyword"] == "kw1"
    assert body["kpis"]["monitored_keywords"] == 1
    assert body["kpis"]["changed_up"] == 1


def test_baidu_keyword_history_captcha_and_news_flags(client: TestClient, monitor_db: Path):
    """captcha_hit=True / news_present=True 在 KPI 里被统计到。"""
    tid = _seed_baidu_task(client)
    now = datetime.now()
    _seed_baidu_result(tid, checked_at=now, matched_count=2, best_rank=1,
                       captcha_hit=True, news_present=True)
    resp = client.get("/api/monitor/history/baidu-keyword?range=7d")
    k = resp.json()["kpis"]
    assert k["captcha_count"] == 1
    assert k["news_present_count"] == 1


def test_baidu_keyword_history_invalid_range_400(client: TestClient, monitor_db: Path):
    resp = client.get("/api/monitor/history/baidu-keyword?range=2d")
    assert resp.status_code == 400
    assert "range" in resp.json()["detail"]
