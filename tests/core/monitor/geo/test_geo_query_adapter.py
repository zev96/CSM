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
    assert progress[-1] == (4, 4)                # 2 关键词 × 2 平台

    # 落库
    rid = storage.latest_result(tid).task_id  # sanity
    from csm_core.monitor.geo import storage as geo_storage
    conn = storage.get_conn()
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 4


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
    conn = storage.get_conn()
    rows = conn.execute("SELECT platform, status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()
    statuses = {r["platform"]: r["status"] for r in rows}
    assert statuses["tongyi"] == "ok"
    assert statuses["kimi"] == "error"
