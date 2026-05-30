from __future__ import annotations
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell, ClassifiedCitation


@pytest.fixture
def fresh_db(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield tmp_path / "monitor.db"
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


def test_v7_tables_exist(fresh_db):
    conn = storage.get_conn()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "geo_cells" in names
    assert "geo_citations" in names


def _seed_run(fresh_db) -> int:
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="小鹏卡位", target_url="geo://小鹏",
        config={"brand": "小鹏"}))
    rid = storage.save_result(MonitorResult(
        task_id=tid, checked_at=__import__("datetime").datetime.utcnow(),
        status="ok", rank=2, metric={}))
    cells = [
        GeoCell(platform="tongyi", keyword="新能源SUV", mentioned=True, rank=1, sentiment="pos",
                citations=[ClassifiedCitation(url="https://zhihu.com/a", domain="zhihu.com", source_type="知乎"),
                           ClassifiedCitation(url="https://xiaohongshu.com/b", domain="xiaohongshu.com", source_type="小红书")]),
        GeoCell(platform="kimi", keyword="新能源SUV", mentioned=False, rank=-1,
                citations=[ClassifiedCitation(url="https://zhihu.com/c", domain="zhihu.com", source_type="知乎")]),
    ]
    geo_storage.record_run(rid, tid, cells)
    return tid


def test_record_run_persists_cells_and_citations(fresh_db):
    tid = _seed_run(fresh_db)
    conn = storage.get_conn()
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM geo_citations WHERE task_id=?", (tid,)).fetchone()[0] == 3


def test_citation_leaderboard_ranks_by_freq(fresh_db):
    tid = _seed_run(fresh_db)
    board = geo_storage.citation_leaderboard(tid, days=3650)
    # zhihu.com 出现 2 次，xiaohongshu.com 1 次
    assert board[0]["domain"] == "zhihu.com"
    assert board[0]["count"] == 2
    assert board[0]["source_type"] == "知乎"


def test_citation_leaderboard_survives_comma_in_keyword(fresh_db):
    import datetime
    tid = storage.create_task(MonitorTask(type="geo_query", name="t", target_url="geo://b",
                                          config={"brand": "b"}))
    rid = storage.save_result(MonitorResult(task_id=tid, checked_at=datetime.datetime.utcnow(),
                                            status="ok", rank=1, metric={}))
    kw = "20万以内, 新能源SUV"  # 关键词本身含逗号
    geo_storage.record_run(rid, tid, [GeoCell(platform="tongyi", keyword=kw, mentioned=True, rank=1,
        citations=[ClassifiedCitation(url="https://zhihu.com/x", domain="zhihu.com", source_type="知乎")])])
    board = geo_storage.citation_leaderboard(tid, days=3650)
    assert board[0]["keywords"] == [kw]   # 不被逗号拆碎


def test_cells_for_run_hydrates_citations(fresh_db):
    tid = _seed_run(fresh_db)
    # latest_result returns a MonitorResult; fetch result_id via geo_cells rows
    conn = storage.get_conn()
    result_id = conn.execute("SELECT DISTINCT result_id FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0]
    cells = geo_storage.cells_for_run(result_id)
    assert len(cells) == 2
    tongyi = [c for c in cells if c["platform"] == "tongyi"][0]
    assert len(tongyi["citations"]) == 2
