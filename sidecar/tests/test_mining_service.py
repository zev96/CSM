"""mining_service tests using a fake runner."""
import threading
import time
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import mining_service


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    monkeypatch.setattr(monitor_storage, "_local", threading.local())
    monitor_storage.init_db(tmp_path / "monitor.db")
    # Reset service singletons.
    mining_service._executor = None
    mining_service._runner = None
    mining_service._active_job_id = None
    yield
    mining_service.shutdown()


def test_init_idempotent():
    mining_service.init()
    mining_service.init()
    assert not mining_service.is_busy()


def test_submit_runs_and_completes(monkeypatch):
    class StubRunner:
        def __init__(self, *a, **kw): pass
        def run(self, job_id):
            ms.update_platform_progress(job_id, "bilibili", got=1, target=1, phase="done")
            ms.finalize_job(job_id)
        def register_cancel_event(self, job_id):
            return threading.Event()
        def cancel(self, job_id): return False

    monkeypatch.setattr(mining_service, "MiningRunner", StubRunner)
    mining_service.init()
    jid = mining_service.submit_job("k", ["bilibili"], 50)
    # Wait up to 2s for the executor to flush.
    for _ in range(20):
        if not mining_service.is_busy():
            break
        time.sleep(0.1)
    assert not mining_service.is_busy()
    assert ms.get_job(jid)["status"] in {"done", "partial_done", "failed"}


def test_submit_rejects_when_busy(monkeypatch):
    block = threading.Event()
    class BlockingRunner:
        def __init__(self, *a, **kw): pass
        def run(self, job_id):
            block.wait(timeout=2.0)
            ms.finalize_job(job_id)
        def register_cancel_event(self, job_id):
            return threading.Event()
        def cancel(self, job_id): return False

    monkeypatch.setattr(mining_service, "MiningRunner", BlockingRunner)
    mining_service.init()
    jid1 = mining_service.submit_job("k1", ["bilibili"], 50)
    # Loop until the worker enters run().
    for _ in range(20):
        if mining_service.is_busy():
            break
        time.sleep(0.05)
    with pytest.raises(RuntimeError, match="busy"):
        mining_service.submit_job("k2", ["bilibili"], 50)
    block.set()
    for _ in range(40):
        if not mining_service.is_busy():
            break
        time.sleep(0.05)


def test_cancel_when_no_active_job_returns_false():
    mining_service.init()
    assert mining_service.cancel_job(999) is False


def test_submit_job_brand_keywords_round_trips(monkeypatch):
    """submit_job with brand_keywords persists them; get_job reads them back."""
    class StubRunner:
        def __init__(self, *a, **kw): pass
        def run(self, job_id):
            ms.finalize_job(job_id)
        def register_cancel_event(self, job_id):
            return threading.Event()
        def cancel(self, job_id): return False

    monkeypatch.setattr(mining_service, "MiningRunner", StubRunner)
    mining_service.init()
    jid = mining_service.submit_job("扫地机器人", ["douyin"], 50, brand_keywords=["石头"])
    job = ms.get_job(jid)
    assert job is not None
    assert job["brand_keywords"] == ["石头"]
