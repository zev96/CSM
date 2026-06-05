"""GEO 汇总曝光率端点：全局 soc = Σmentioned/Σok_cells + 较上一窗口 delta（首页 GEO 仪表盘卡）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell


def _cell(kw: str, *, mentioned: bool, status: str = "ok") -> GeoCell:
    return GeoCell(
        platform="tongyi", keyword=kw, mentioned=mentioned,
        rank=1 if mentioned else -1, sentiment="pos" if mentioned else "na",
        answer_text="", status=status, raw={}, recommended=[], summary="", citations=[],
    )


def test_geo_exposure_summary_global_soc(client: TestClient, monitor_db: Path):
    now = datetime.now()
    # 4 个 ok cell，2 个 mentioned → soc 0.5
    geo_storage.record_run(1, now, [
        _cell("a", mentioned=True), _cell("b", mentioned=True),
        _cell("c", mentioned=False), _cell("d", mentioned=False),
    ])
    r = client.get("/api/monitor/geo/summary", params={"range": "7d"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["soc"] == 0.5
    assert body["ok_cells"] == 4 and body["mentioned"] == 2
    assert body["band"] in ("hidden", "weak", "strong")


def test_geo_exposure_summary_excludes_errored_cells(client: TestClient, monitor_db: Path):
    """status!='ok' 的 cell 不计入分母（采集失败 ≠ 问了没提及）。"""
    now = datetime.now()
    geo_storage.record_run(1, now, [
        _cell("a", mentioned=True),                      # ok + mentioned
        _cell("b", mentioned=False),                     # ok + 未提及
        _cell("c", mentioned=False, status="error"),     # 失败 → 不计分母
    ])
    body = client.get("/api/monitor/geo/summary", params={"range": "7d"}).json()
    assert body["ok_cells"] == 2 and body["mentioned"] == 1
    assert body["soc"] == 0.5


def test_geo_exposure_summary_empty(client: TestClient, monitor_db: Path):
    body = client.get("/api/monitor/geo/summary", params={"range": "7d"}).json()
    assert body["soc"] == 0.0 and body["ok_cells"] == 0 and body["delta"] == 0.0
