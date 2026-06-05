"""全局高权重信源榜：跨所有 geo 任务聚合 + 排名周对比（首页高权重信源卡）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell, ClassifiedCitation


def _cell(kw: str, domains: list[str], *, mentioned: bool = True, status: str = "ok") -> GeoCell:
    return GeoCell(
        platform="tongyi", keyword=kw, mentioned=mentioned, rank=1,
        sentiment="pos", answer_text="x", status=status, raw={},
        recommended=[], summary="",
        citations=[
            ClassifiedCitation(url=f"https://{d}/a", title="t", domain=d, source_type="新闻网站")
            for d in domains
        ],
    )


def test_global_leaderboard_aggregates_across_tasks(monitor_db: Path):
    """task_id=None → 跨所有任务聚合域名频次。"""
    now = datetime.now()
    geo_storage.record_run(101, now, [_cell("扫地机", ["smzdm.com", "zhihu.com"])])
    geo_storage.record_run(202, now, [_cell("吸尘器", ["smzdm.com"])])

    board = geo_storage.citation_leaderboard(task_id=None, days=7)

    domains = [b["domain"] for b in board]
    assert "smzdm.com" in domains and "zhihu.com" in domains
    smzdm = next(b for b in board if b["domain"] == "smzdm.com")
    assert smzdm["count"] == 2  # 101 + 202 两个任务合计


def test_global_leaderboard_task_scoped_still_works(monitor_db: Path):
    """既有单任务调用不回归（task_id 给具体值时只看该任务）。"""
    now = datetime.now()
    geo_storage.record_run(1, now, [_cell("k", ["a.com"])])
    geo_storage.record_run(2, now, [_cell("k", ["b.com"])])

    board1 = geo_storage.citation_leaderboard(task_id=1, days=7)
    assert [b["domain"] for b in board1] == ["a.com"]


def test_global_leaderboard_endpoint_rank_and_delta(client: TestClient, monitor_db: Path):
    """端点返回 rank + rank_prev/rank_delta；上一窗口无数据 → 新进(None)。"""
    now = datetime.now()
    geo_storage.record_run(1, now, [_cell("k", ["smzdm.com", "smzdm.com"])])
    geo_storage.record_run(1, now, [_cell("k", ["zhihu.com"])])

    r = client.get("/api/monitor/geo/citations/leaderboard", params={"days": 7, "limit": 8})
    assert r.status_code == 200, r.text
    board = r.json()["leaderboard"]

    assert board[0]["domain"] == "smzdm.com"
    assert board[0]["rank"] == 1
    # 上一窗口 [14d, 7d) 无数据 → 新进
    assert board[0]["rank_prev"] is None
    assert board[0]["rank_delta"] is None
