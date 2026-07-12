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


def test_baidu_keyword_row_checked_at_stays_utc(client: TestClient, monitor_db: Path):
    """R6 修正：keyword_rows[].checked_at 仍是原始 UTC —— daily_series 的本地日桶
    只用旁路的 checked_at_local，绝不能把本地时间喂进 _iso_utc（它只归一化 aware
    值，naive-本地会被当 UTC 盖 Z，偏移一个时区）。"""
    tid = _seed_baidu(client)
    utc_at = datetime(2026, 7, 10, 2, 0, 0)  # naive UTC（运行器按 UTC 存）
    _res_baidu(tid, utc_at, "扫地机", 1, 3)
    out = history_service.get_baidu_keyword_history("30d")
    row = next(r for r in out["keywords"] if r["search_keyword"] == "扫地机")
    parsed = storage._parse_iso(row["checked_at"])  # noqa: SLF001
    assert parsed == utc_at, f"checked_at 应为原始 UTC {utc_at}，实际 {row['checked_at']}"


def test_baidu_daily_series_buckets_by_local_day(client: TestClient, monitor_db: Path):
    """R6：daily_series 按**本地日**分桶（与前端本地日 + KPI 口径一致），而不是
    UTC 日。跨日的结果（本地凌晨/深夜、UTC 落在相邻日）不应错分到相邻桶。"""
    import pytest
    from datetime import timezone as _tz
    offset = datetime.now().astimezone().utcoffset()
    if offset is None or offset == timedelta(0):
        pytest.skip("UTC 机器无本地/UTC 日偏移，测不出")
    hour = 6 if offset > timedelta(0) else 22  # 让本地时刻与 UTC 落在相邻日

    tid = _seed_baidu(client)
    target_local = (datetime.now() - timedelta(days=2)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    target_utc = target_local.astimezone(_tz.utc).replace(tzinfo=None)  # 运行器按 UTC 存
    d_local = target_local.strftime("%Y-%m-%d")
    d_utc = target_utc.strftime("%Y-%m-%d")
    assert d_local != d_utc, "构造前提：本地日与 UTC 日必须不同"

    _res_baidu(tid, target_utc, "扫地机", 1, 3)
    out = history_service.get_baidu_keyword_history("30d")
    first_hit = next((b["date"] for b in out["daily_series"] if b["avg_match_rate"] > 0), None)
    assert first_hit == d_local, f"应按本地日 {d_local} 分桶，实际 {first_hit}（UTC 日 {d_utc}）"


def test_zhihu_search_changed_prev_field_present_when_empty(client: TestClient, monitor_db: Path):
    out = history_service.get_zhihu_search_history("7d")
    assert out["kpis"]["changed_prev"] == 0
