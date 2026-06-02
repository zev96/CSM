from __future__ import annotations
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.geo.models import GeoAnswer, Citation
from csm_core.monitor.platforms import geo_query as geo_mod


@pytest.fixture
def fresh_db(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


class FakeProvider:
    def __init__(self, platform):
        self.platform = platform
        self.mode = "api"

    def query(self, keyword, *, web_search=True, cancel_token=None):
        return GeoAnswer(platform=self.platform, keyword=keyword,
                         answer_text=f"{self.platform} 推荐 小鹏 G6",
                         citations=[Citation(url="https://zhuanlan.zhihu.com/p/1", title="知乎")])


class FakeClient:
    def complete(self, *, system, user, temperature=None):
        return '{"mentioned":true,"target_rank":1,"sentiment":"pos","recommended":[{"name":"小鹏","position":1}],"summary":"正面"}'


def test_fetch_fans_out_and_records(fresh_db, monkeypatch):
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: FakeProvider(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="小鹏卡位", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["新能源SUV", "智驾车"],
                "platforms": ["tongyi", "kimi"], "extract_provider": "mock"}))
    task = storage.get_task(tid)

    progress = []
    result = geo_mod.ADAPTER.fetch(task, progress_cb=lambda c, t: progress.append((c, t)))

    assert result.status == "ok"
    assert result.rank == 1                      # 全 rank==1 → 中位 1
    assert result.metric["soc"] == 1.0
    assert result.metric["first_rank_rate"] == 1.0
    assert result.metric["error_cells"] == 0     # 全 ok，没有采集失败
    assert result.metric["partial_resume"] is False
    assert progress[0] == (0, 4)                 # 初始 0/total 事件（先于第一个 cell）
    assert progress[-1] == (4, 4)                # 2 关键词 × 2 平台

    # ── Simulate monitor_loop._run_one: the LOOP persists the result, the
    # adapter must NOT. This is the C1 regression guard — if the adapter
    # ever calls save_result again, this run yields 2 monitor_results rows.
    from csm_core.monitor.geo import storage as geo_storage
    storage.save_result(result)
    conn = storage.get_conn()
    assert conn.execute(
        "SELECT count(*) FROM monitor_results WHERE task_id=?", (tid,)
    ).fetchone()[0] == 1                          # 单写：loop 存一行，adapter 不自存

    # geo 明细落库 + 下钻按 (task_id, checked_at) 关联回这 4 个 cell。
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 4
    drill = geo_storage.cells_for_run(tid, result.checked_at)
    assert len(drill) == 4


def test_all_cells_failed_marks_run_failed(fresh_db, monkeypatch):
    # I1: when BOTH platforms raise, every cell is error → the run must be
    # status="failed" (not ok+rank=-1), so notify.should_alert returns False
    # and the user doesn't get a false "排名跌出 Top-N" alert.
    class Boom(FakeProvider):
        def query(self, *a, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: Boom(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["k1", "k2"], "platforms": ["tongyi", "kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))

    assert result.status == "failed"             # 全失败 → failed
    assert result.rank == -1
    assert result.metric["error_cells"] == 4     # 2 关键词 × 2 平台，全错
    assert result.error_message                  # 带首个失败 cell 的错误摘要

    # cells 仍然落库（数据不丢），且下钻能取回。
    from csm_core.monitor.geo import storage as geo_storage
    drill = geo_storage.cells_for_run(tid, result.checked_at)
    assert len(drill) == 4
    assert all(c["status"] == "error" for c in drill)


def test_one_provider_error_does_not_kill_run(fresh_db, monkeypatch):
    def picker(p):
        if p == "kimi":
            class Boom(FakeProvider):
                def query(self, *a, **k):
                    raise RuntimeError("boom")
            return Boom(p)
        return FakeProvider(p)
    monkeypatch.setattr(geo_mod, "get_provider", picker)
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                 # 部分失败不整体失败
    assert result.metric["error_cells"] == 1     # 仅 kimi 失败 → I2 surface
    conn = storage.get_conn()
    rows = conn.execute("SELECT platform, status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()
    statuses = {r["platform"]: r["status"] for r in rows}
    assert statuses["tongyi"] == "ok"
    assert statuses["kimi"] == "error"
