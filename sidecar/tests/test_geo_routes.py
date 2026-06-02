"""GEO 只读聚合端点。复用项目既有 TestClient fixture 风格（参考
sidecar/tests/test_baidu_keyword.py / conftest）。

auth：``client`` fixture（conftest）在 app lifespan 启动后把
``Authorization: Bearer <auth.get_token()>`` 贴到每个请求上，满足 router
级别的 ``dependencies=[RequireToken]``。本测试不另造 auth 旁路。
"""
from __future__ import annotations

import datetime
import threading
from pathlib import Path

import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import ClassifiedCitation, GeoCell


@pytest.fixture
def geo_seeded(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    tid = storage.create_task(MonitorTask(type="geo_query", name="小鹏", target_url="geo://小鹏",
                                          config={"brand": "小鹏"}))
    checked_at = datetime.datetime.utcnow()
    storage.save_result(MonitorResult(task_id=tid, checked_at=checked_at,
                                      status="ok", rank=1, metric={"soc": 1.0}))
    geo_storage.record_run(tid, checked_at, [GeoCell(platform="tongyi", keyword="k", mentioned=True, rank=1,
        citations=[ClassifiedCitation(url="https://zhihu.com/a", domain="zhihu.com", source_type="知乎")])])
    # checked_at 是 cells 下钻端点的关联键（geo_storage._iso 得到存库 ISO 串）。
    yield tid, geo_storage._iso(checked_at)
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


def test_citation_leaderboard_endpoint(client, geo_seeded):
    tid, _ = geo_seeded
    r = client.get(f"/api/monitor/geo/{tid}/citations", params={"days": 3650})
    assert r.status_code == 200
    board = r.json()["leaderboard"]
    assert board[0]["domain"] == "zhihu.com"
    assert board[0]["count"] == 1


def test_cells_endpoint_correlates_by_checked_at(client, geo_seeded):
    tid, checked_at = geo_seeded
    r = client.get(f"/api/monitor/geo/{tid}/cells", params={"checked_at": checked_at})
    assert r.status_code == 200
    cells = r.json()["cells"]
    assert len(cells) == 1
    assert cells[0]["platform"] == "tongyi"


def test_cells_endpoint_tolerates_missing_trailing_z(client, geo_seeded):
    # /api/monitor/results 回传的 checked_at 缺尾 Z（geo_cells 存库带 Z）。
    # cells_for_run 现在 rtrim 'Z' 双边归一，少了 Z 也能命中同一批 cell。
    tid, checked_at = geo_seeded
    no_z = checked_at[:-1] if checked_at.endswith("Z") else checked_at
    assert no_z != checked_at  # fixture 确实带 Z
    r = client.get(f"/api/monitor/geo/{tid}/cells", params={"checked_at": no_z})
    assert r.status_code == 200
    assert len(r.json()["cells"]) == 1


def test_latest_cells_endpoint_returns_seeded_cells(client, geo_seeded):
    # L2 卡位仪表盘走的「最近一跑」端点 —— 不传 checked_at，后端用
    # max(checked_at) 解析。返回的 cell 必须带 recommended / summary / citations。
    tid, _ = geo_seeded
    r = client.get(f"/api/monitor/geo/{tid}/latest-cells")
    assert r.status_code == 200
    cells = r.json()["cells"]
    assert len(cells) == 1
    cell = cells[0]
    assert cell["platform"] == "tongyi"
    assert cell["keyword"] == "k"
    # hydration 字段齐全（即便本 fixture 的 recommended/summary 为空也得在）。
    assert "recommended" in cell
    assert "summary" in cell
    assert [c["domain"] for c in cell["citations"]] == ["zhihu.com"]


def test_geo_export_xlsx(client, geo_seeded):
    tid, _ = geo_seeded
    r = client.get(f"/api/monitor/geo/{tid}/export?days=3650")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"   # xlsx = zip, magic bytes PK


def test_latest_cells_endpoint_hydrates_recommended_and_summary(client, tmp_path):
    # 单独 seed 一跑带 recommended + summary，确认 latest-cells 把它们解析回来
    # （L2 下钻要展示「谁排第 1/第 2、自己在第几」+ AI 一句话总评）。
    from csm_core.monitor.geo.models import RecommendedEntity

    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    try:
        tid = storage.create_task(MonitorTask(type="geo_query", name="小鹏", target_url="geo://小鹏",
                                              config={"brand": "小鹏"}))
        checked_at = datetime.datetime.utcnow()
        storage.save_result(MonitorResult(task_id=tid, checked_at=checked_at,
                                          status="ok", rank=2, metric={}))
        geo_storage.record_run(tid, checked_at, [GeoCell(
            platform="tongyi", keyword="新能源SUV", mentioned=True, rank=2, sentiment="pos",
            citations=[ClassifiedCitation(url="https://zhihu.com/a", domain="zhihu.com", source_type="知乎")],
            recommended=[RecommendedEntity(name="A", position=1, is_target=False),
                         RecommendedEntity(name="小鹏", position=2, is_target=True)],
            summary="小鹏在新能源SUV里口碑居前")])
        r = client.get(f"/api/monitor/geo/{tid}/latest-cells")
        assert r.status_code == 200
        cell = r.json()["cells"][0]
        assert cell["summary"] == "小鹏在新能源SUV里口碑居前"
        rec = cell["recommended"]
        assert [e["name"] for e in rec] == ["A", "小鹏"]
        target = [e for e in rec if e["is_target"]]
        assert len(target) == 1 and target[0]["name"] == "小鹏"
    finally:
        conn = getattr(storage_mod._local, "conn", None)
        if conn is not None:
            conn.close()
        storage_mod._db_path = None
        storage_mod._initialized = False
