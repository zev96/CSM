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


def test_cells_for_run_tolerates_missing_trailing_z(fresh_db):
    # geo_cells 存库串带尾 Z（_iso），但 /api/monitor/results 回传的
    # checked_at 不带 Z。cells_for_run 现在 rtrim 'Z' 双边归一 —— 少了 Z
    # 也能命中同一批 cell，而不是精确匹配失败返回 0 条。
    tid, checked_at = _seed_run(fresh_db)
    iso = geo_storage._iso(checked_at)
    assert iso.endswith("Z")
    cells = geo_storage.cells_for_run(tid, iso[:-1])  # 去掉尾 Z
    assert len(cells) == 2


def test_cells_for_latest_run_returns_most_recent(fresh_db):
    # cells_for_latest_run 用 max(checked_at) 解析最近一跑，不需要传 checked_at。
    tid, first_checked = _seed_run(fresh_db)
    # 再 seed 一跑（更晚的 checked_at），只放一个 cell，确认 latest 取到的是它。
    later = first_checked + datetime.timedelta(seconds=5)
    storage.save_result(MonitorResult(task_id=tid, checked_at=later, status="ok", rank=1, metric={}))
    geo_storage.record_run(tid, later, [GeoCell(
        platform="tongyi", keyword="最新词", mentioned=True, rank=1, sentiment="pos",
        citations=[ClassifiedCitation(url="https://example.com/z", domain="example.com", source_type="其他")],
        recommended=[RecommendedEntity(name="小鹏", position=1, is_target=True)],
        summary="最新一跑")])
    cells = geo_storage.cells_for_latest_run(tid)
    assert len(cells) == 1  # 只有最近这跑的单个 cell，不混入第一跑的两条
    assert cells[0]["keyword"] == "最新词"
    assert cells[0]["summary"] == "最新一跑"
    assert cells[0]["recommended"][0]["name"] == "小鹏"
    assert [c["domain"] for c in cells[0]["citations"]] == ["example.com"]


def test_cells_for_latest_run_empty_when_no_runs(fresh_db):
    tid = storage.create_task(MonitorTask(type="geo_query", name="无运行", target_url="geo://x",
                                          config={"brand": "x"}))
    assert geo_storage.cells_for_latest_run(tid) == []


def test_v7_migration_adds_extraction_json_to_preexisting_table(tmp_path):
    """老库早先建了不含 extraction_json 的 geo_cells，再次迁移必须 ALTER 补列。

    回归：就地改 CREATE TABLE 的列对已存在表是 no-op，会导致读 extraction_json
    时 OperationalError（实测 /latest-cells 500）。apply_v7_migration 须幂等补列。
    """
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    try:
        # 模拟「extraction_json 出现之前」建的 geo_cells（缺该列）。
        conn.execute(
            """CREATE TABLE geo_cells (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
                checked_at TEXT NOT NULL, platform TEXT NOT NULL, keyword TEXT NOT NULL,
                mentioned INTEGER NOT NULL DEFAULT 0, rank INTEGER NOT NULL DEFAULT -1,
                sentiment TEXT NOT NULL DEFAULT 'na', answer_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok', raw_json TEXT NOT NULL DEFAULT '{}')"""
        )
        cols_before = {r[1] for r in conn.execute("PRAGMA table_info(geo_cells)")}
        assert "extraction_json" not in cols_before
        geo_storage.apply_v7_migration(conn)  # 幂等：建 geo_citations + ALTER 补列
        cols_after = {r[1] for r in conn.execute("PRAGMA table_info(geo_cells)")}
        assert "extraction_json" in cols_after
        # 再跑一次不应报错（ALTER 已存在列会被 _ensure_column 跳过）。
        geo_storage.apply_v7_migration(conn)
    finally:
        conn.close()
