"""Tests for storage — sqlite persistence layer."""
from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path

import pytest

# Storage uses module-level singleton state. Each test gets a fresh
# tempdir + a brand-new sqlite db, but we must reset the module-level
# guards between tests so init_db doesn't refuse to switch paths.
import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask


@pytest.fixture
def fresh_db(tmp_path: Path):
    # Reset the module-level singleton guards so tests are isolated.
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield tmp_path / "monitor.db"
    # Close any thread-local connection so Windows can delete tmp_path.
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


class TestInitAndMigrate:
    def test_creates_db_file(self, fresh_db: Path):
        assert fresh_db.exists()

    def test_idempotent_init(self, fresh_db: Path, tmp_path: Path):
        # Calling init_db with the same path is a no-op.
        storage.init_db(fresh_db)

    def test_rejects_path_change(self, fresh_db: Path, tmp_path: Path):
        with pytest.raises(RuntimeError):
            storage.init_db(tmp_path / "other.db")


class TestTasks:
    def test_create_and_list(self, fresh_db: Path):
        tid = storage.create_task(MonitorTask(
            type="zhihu_question",
            name="任务A",
            target_url="https://www.zhihu.com/question/123",
            config={"target_brand": "ACME", "top_n": 5},
            schedule_cron="09:30",
        ))
        assert tid > 0
        all_tasks = storage.list_tasks()
        assert len(all_tasks) == 1
        assert all_tasks[0].name == "任务A"
        assert all_tasks[0].config["target_brand"] == "ACME"

    def test_upsert_on_unique_collision(self, fresh_db: Path):
        # Same (type, target_url) — should update name + config in place.
        storage.create_task(MonitorTask(
            type="zhihu_question",
            name="原始",
            target_url="https://www.zhihu.com/question/123",
            config={"target_brand": "A", "top_n": 5},
        ))
        storage.create_task(MonitorTask(
            type="zhihu_question",
            name="覆盖",
            target_url="https://www.zhihu.com/question/123",
            config={"target_brand": "B", "top_n": 10},
        ))
        rows = storage.list_tasks()
        assert len(rows) == 1
        assert rows[0].name == "覆盖"
        assert rows[0].config["target_brand"] == "B"

    def test_filter_by_type_and_enabled(self, fresh_db: Path):
        storage.create_task(MonitorTask(
            type="zhihu_question", name="z", target_url="https://www.zhihu.com/question/1",
            config={"target_brand": "x"}, enabled=True,
        ))
        storage.create_task(MonitorTask(
            type="bilibili_comment", name="b", target_url="https://www.bilibili.com/video/BV111",
            config={"my_comment_text": "x"}, enabled=False,
        ))
        zhihu_only = storage.list_tasks(type="zhihu_question")
        assert len(zhihu_only) == 1
        enabled_only = storage.list_tasks(enabled_only=True)
        assert len(enabled_only) == 1
        assert enabled_only[0].type == "zhihu_question"

    def test_delete_cascades_results(self, fresh_db: Path):
        tid = storage.create_task(MonitorTask(
            type="zhihu_question", name="tmp", target_url="https://www.zhihu.com/question/9",
            config={"target_brand": "x"},
        ))
        storage.save_result(MonitorResult(
            task_id=tid, checked_at=datetime.utcnow(), status="ok", rank=1, metric={},
        ))
        assert len(storage.list_results(tid)) == 1
        storage.delete_task(tid)
        # Re-create to be sure the DELETE cascaded.
        new_tid = storage.create_task(MonitorTask(
            type="zhihu_question", name="t2", target_url="https://www.zhihu.com/question/9",
            config={"target_brand": "x"},
        ))
        assert storage.list_results(new_tid) == []


class TestResults:
    def test_save_updates_task_last_status(self, fresh_db: Path):
        tid = storage.create_task(MonitorTask(
            type="zhihu_question", name="t", target_url="https://www.zhihu.com/question/1",
            config={"target_brand": "x"},
        ))
        storage.save_result(MonitorResult(
            task_id=tid, checked_at=datetime.utcnow(), status="ok", rank=3, metric={"a": 1},
        ))
        task = storage.get_task(tid)
        assert task.last_status == "ok"
        assert task.last_check_at is not None

    def test_alert_flag_persisted(self, fresh_db: Path):
        tid = storage.create_task(MonitorTask(
            type="zhihu_question", name="t", target_url="https://www.zhihu.com/question/2",
            config={"target_brand": "x"},
        ))
        storage.save_result(
            MonitorResult(task_id=tid, checked_at=datetime.utcnow(), status="ok", rank=-1, metric={}),
            alert_triggered=True,
        )
        assert storage.last_alert_at(tid) is not None


class TestCredentials:
    def test_pick_orders_by_health(self, fresh_db: Path):
        a = storage.add_credential("zhihu_question", "AAA", label="acc1")
        b = storage.add_credential("zhihu_question", "BBB", label="acc2")
        storage.mark_credential_used(a, success=False)
        storage.mark_credential_used(a, success=False)
        rows = storage.list_credentials("zhihu_question")
        # The one with fewer failures should sort first.
        assert rows[0]["id"] == b
