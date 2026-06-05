"""ranking 端点的 changed_prev：上一个窗口的异动数，供大数字卡算「较上周净增减」徽章。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult
from csm_sidecar.services import history_service


# ── zhihu_question（per-task）──────────────────────────────────────────────

def _seed_zhihu_q(client: TestClient) -> int:
    body = {"type": "zhihu_question", "name": "知乎问题-X", "target_url": "https://zhihu.com/q/1",
            "config": {"top_n": 10, "target_brand": "石头"}, "schedule_cron": "manual", "enabled": True}
    return client.post("/api/monitor/tasks", json=body).json()["id"]


def _res_q(tid: int, at: datetime, mc: int):
    storage.save_result(MonitorResult(task_id=tid, checked_at=at, status="ok", rank=1,
        metric={"matched_count": mc, "matched_ranks": [1] * mc, "top_n": 10}, error_message=""))


def test_zhihu_ranking_changed_prev_counts_older_window(client: TestClient, monitor_db: Path):
    tid = _seed_zhihu_q(client)
    now = datetime.now()
    _res_q(tid, now - timedelta(days=9), 2)
    _res_q(tid, now - timedelta(days=8), 4)   # 上一窗口内 up（4 vs 2）
    _res_q(tid, now, 4)                        # 本窗口
    out = history_service.get_zhihu_ranking_history("7d")
    assert out["kpis"]["changed_prev"] == 1


# ── baidu_keyword（per-keyword）────────────────────────────────────────────

def _seed_baidu(client: TestClient, kw: str = "扫地机") -> int:
    body = {"type": "baidu_keyword", "name": "百度-X", "target_url": "https://baidu.com",
            "config": {"search_keywords": [kw], "target_brand": "石头"},
            "schedule_cron": "manual", "enabled": True}
    return client.post("/api/monitor/tasks", json=body).json()["id"]


def _res_baidu(tid: int, at: datetime, kw: str, mc: int, fr: int):
    storage.save_result(MonitorResult(task_id=tid, checked_at=at, status="ok", rank=fr,
        metric={"keywords": [{"keyword": kw, "default_matched_count": mc, "default_first_rank": fr,
                              "default_results": [], "news_results": [], "news_present": False}],
                "search_keywords": [kw], "target_brand": "石头"}, error_message=""))


def test_baidu_changed_prev_counts_older_window(client: TestClient, monitor_db: Path):
    tid = _seed_baidu(client)
    now = datetime.now()
    _res_baidu(tid, now - timedelta(days=9), "扫地机", 1, 5)
    _res_baidu(tid, now - timedelta(days=8), "扫地机", 3, 2)   # up
    _res_baidu(tid, now, "扫地机", 3, 2)
    out = history_service.get_baidu_keyword_history("7d")
    assert out["kpis"]["changed_prev"] == 1


def test_baidu_changed_prev_field_present_when_empty(client: TestClient, monitor_db: Path):
    out = history_service.get_baidu_keyword_history("7d")
    assert out["kpis"]["changed_prev"] == 0


def test_zhihu_search_changed_prev_field_present_when_empty(client: TestClient, monitor_db: Path):
    out = history_service.get_zhihu_search_history("7d")
    assert out["kpis"]["changed_prev"] == 0
