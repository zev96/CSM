"""Tests for the alert decision."""
from __future__ import annotations
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.notify import should_alert


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


def _task(tid: int = 1) -> MonitorTask:
    return MonitorTask(
        id=tid, type="zhihu_question", name="t",
        target_url="https://www.zhihu.com/question/1",
        config={"target_brand": "x"},
    )


class TestShouldAlert:
    def test_failed_status_never_alerts(self, fresh_db):
        # Insert the task so should_alert can reference it via storage.
        storage.create_task(_task())
        result = MonitorResult(task_id=1, checked_at=datetime.utcnow(),
                               status="failed", rank=-1)
        assert should_alert(_task(), result, alert_top_n=5, cooldown_hours=24) is False

    def test_rank_inside_top_n_does_not_alert(self, fresh_db):
        storage.create_task(_task())
        result = MonitorResult(task_id=1, checked_at=datetime.utcnow(),
                               status="ok", rank=3)
        assert should_alert(_task(), result, alert_top_n=5, cooldown_hours=24) is False

    def test_rank_minus_one_alerts(self, fresh_db):
        storage.create_task(_task())
        result = MonitorResult(task_id=1, checked_at=datetime.utcnow(),
                               status="ok", rank=-1)
        assert should_alert(_task(), result, alert_top_n=5, cooldown_hours=24) is True

    def test_cooldown_suppresses_repeat_alert(self, fresh_db):
        storage.create_task(_task())
        # First alert: persisted with alert_triggered=True.
        first = MonitorResult(task_id=1, checked_at=datetime.utcnow(),
                              status="ok", rank=-1)
        storage.save_result(first, alert_triggered=True)
        # Second result moments later — cooldown should swallow it.
        second = MonitorResult(task_id=1, checked_at=datetime.utcnow(),
                               status="ok", rank=-1)
        assert should_alert(_task(), second, alert_top_n=5, cooldown_hours=24) is False
