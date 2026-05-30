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
