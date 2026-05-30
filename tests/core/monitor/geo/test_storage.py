from __future__ import annotations
import datetime
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell, ClassifiedCitation, RecommendedEntity


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


def _seed_run(fresh_db) -> tuple[int, datetime.datetime]:
    """Create a task + one run's cells. Returns (task_id, checked_at).

    The same ``checked_at`` is stamped on the MonitorResult and passed to
    record_run — that pair is the run's correlation key now that geo_cells
    no longer FK monitor_results(id). Callers use the returned datetime to
    drill down via cells_for_run(task_id, checked_at).
    """
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="小鹏卡位", target_url="geo://小鹏",
        config={"brand": "小鹏"}))
    checked_at = datetime.datetime.utcnow()
    storage.save_result(MonitorResult(
        task_id=tid, checked_at=checked_at,
        status="ok", rank=2, metric={}))
    cells = [
        GeoCell(platform="tongyi", keyword="新能源SUV", mentioned=True, rank=1, sentiment="pos",
                citations=[ClassifiedCitation(url="https://zhihu.com/a", domain="zhihu.com", source_type="知乎"),
                           ClassifiedCitation(url="https://xiaohongshu.com/b", domain="xiaohongshu.com", source_type="小红书")],
                recommended=[RecommendedEntity(name="A", position=1, is_target=False),
                             RecommendedEntity(name="小鹏", position=2, is_target=True)],
                summary="小鹏在新能源SUV里口碑居前"),
        GeoCell(platform="kimi", keyword="新能源SUV", mentioned=False, rank=-1,
                citations=[ClassifiedCitation(url="https://zhihu.com/c", domain="zhihu.com", source_type="知乎")]),
    ]
    geo_storage.record_run(tid, checked_at, cells)
    return tid, checked_at


def test_record_run_persists_cells_and_citations(fresh_db):
    tid, _ = _seed_run(fresh_db)
    conn = storage.get_conn()
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM geo_citations WHERE task_id=?", (tid,)).fetchone()[0] == 3


def test_citation_leaderboard_ranks_by_freq(fresh_db):
    tid, _ = _seed_run(fresh_db)
    board = geo_storage.citation_leaderboard(tid, days=3650)
    # zhihu.com 出现 2 次，xiaohongshu.com 1 次
    assert board[0]["domain"] == "zhihu.com"
    assert board[0]["count"] == 2
    assert board[0]["source_type"] == "知乎"


def test_citation_leaderboard_survives_comma_in_keyword(fresh_db):
    tid = storage.create_task(MonitorTask(type="geo_query", name="t", target_url="geo://b",
                                          config={"brand": "b"}))
    checked_at = datetime.datetime.utcnow()
    storage.save_result(MonitorResult(task_id=tid, checked_at=checked_at,
                                      status="ok", rank=1, metric={}))
    kw = "20万以内, 新能源SUV"  # 关键词本身含逗号
    geo_storage.record_run(tid, checked_at, [GeoCell(platform="tongyi", keyword=kw, mentioned=True, rank=1,
        citations=[ClassifiedCitation(url="https://zhihu.com/x", domain="zhihu.com", source_type="知乎")])])
    board = geo_storage.citation_leaderboard(tid, days=3650)
    assert board[0]["keywords"] == [kw]   # 不被逗号拆碎


def test_cells_for_run_hydrates_citations(fresh_db):
    tid, checked_at = _seed_run(fresh_db)
    # Drill-down correlates by (task_id, checked_at) — no result_id FK anymore.
    cells = geo_storage.cells_for_run(tid, checked_at)
    assert len(cells) == 2
    tongyi = [c for c in cells if c["platform"] == "tongyi"][0]
    assert len(tongyi["citations"]) == 2


def test_cells_for_run_hydrates_recommended_and_summary(fresh_db):
    # L2 下钻要展示「谁排第 1/第 2、自己在第几」+ AI 一句话总评，
    # 所以 cells_for_run 必须把 extraction_json 里的 recommended + summary 解析回来。
    tid, checked_at = _seed_run(fresh_db)
    cells = geo_storage.cells_for_run(tid, checked_at)
    tongyi = [c for c in cells if c["platform"] == "tongyi"][0]
    assert tongyi["summary"] == "小鹏在新能源SUV里口碑居前"
    rec = tongyi["recommended"]
    assert [r["name"] for r in rec] == ["A", "小鹏"]
    assert [r["position"] for r in rec] == [1, 2]
    target = [r for r in rec if r["is_target"]]
    assert len(target) == 1 and target[0]["name"] == "小鹏"
    # 没抽取数据的 cell（kimi 那行）回空列表 + 空串，不报错。
    kimi = [c for c in cells if c["platform"] == "kimi"][0]
    assert kimi["recommended"] == []
    assert kimi["summary"] == ""


def test_cells_for_run_accepts_iso_string(fresh_db):
    # The adapter passes a datetime; a future Task 11 endpoint will pass the
    # stored ISO string back as a query param. Both must hit the same rows.
    tid, checked_at = _seed_run(fresh_db)
    iso = geo_storage._iso(checked_at)
    cells = geo_storage.cells_for_run(tid, iso)
    assert len(cells) == 2
