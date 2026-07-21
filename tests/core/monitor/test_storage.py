"""Tests for storage — sqlite persistence layer."""
from __future__ import annotations
import hashlib
import sqlite3
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

    def test_cooldown_filter_skips_cooled_rows(self, fresh_db: Path):
        """list_credentials(skip_cooldown=True) excludes rows whose
        ``cooldown_until`` is in the future. Used by the rotation picker
        to keep failing cookies out of the rotation for the configured
        cool-off window."""
        import time as _time
        a = storage.add_credential("zhihu_question", "AAA", label="acc1")
        b = storage.add_credential("zhihu_question", "BBB", label="acc2")
        # Cool down `a` 1 hour into the future.
        storage.set_credential_cooldown(a, 3600)

        # Default (skip_cooldown=False) returns both — UI listing path.
        rows_all = storage.list_credentials("zhihu_question")
        assert {r["id"] for r in rows_all} == {a, b}

        # Picker path filters out `a`.
        rows_eligible = storage.list_credentials(
            "zhihu_question", skip_cooldown=True,
        )
        assert {r["id"] for r in rows_eligible} == {b}

    def test_cooldown_expires_via_past_timestamp(self, fresh_db: Path):
        """Setting cooldown_seconds=0 (or a past-now value via the
        column directly) should make the cookie immediately eligible."""
        a = storage.add_credential("zhihu_question", "AAA")
        # Cool 1 second in the future, sleep past it.
        storage.set_credential_cooldown(a, 0)
        rows = storage.list_credentials("zhihu_question", skip_cooldown=True)
        assert rows and rows[0]["id"] == a


class TestCommentTaskIdentity:
    """评论任务身份键 = (type, target_url, 评论文本) —— 批量导入丢行修复。

    背景 bug：monitor_tasks 曾以表级 UNIQUE(type, target_url) 做身份，
    create_task 的 upsert 让「同一视频下的多条评论」互相覆盖 —— 批量导入
    65 行只剩 39 个任务（每个 URL 只留最后一行的评论），且逐行 POST 全部
    返回成功，前端无从察觉。评论留存的监测对象是「视频+某条评论」，身份
    键必须包含评论文本（dedup_key = sha256(strip 后的 my_comment_text)）。
    """

    URL = "https://v.kuaishou.com/7G1uSM4V"

    def _task(self, comment: str, name: str = "0720 - 7G1uSM4V") -> MonitorTask:
        return MonitorTask(
            type="kuaishou_comment",
            name=name,
            target_url=self.URL,
            config={"my_comment_text": comment, "top_n": 5},
        )

    def test_same_url_different_comments_create_separate_tasks(self, fresh_db: Path):
        id1 = storage.create_task(self._task("我推荐希喂，烘焙粮不错"))
        id2 = storage.create_task(self._task("国产粮换了一圈，最后还是选了希喂"))
        assert id1 != id2
        tasks = storage.list_tasks(type="kuaishou_comment")
        assert len(tasks) == 2
        assert {t.config["my_comment_text"] for t in tasks} == {
            "我推荐希喂，烘焙粮不错",
            "国产粮换了一圈，最后还是选了希喂",
        }

    def test_same_url_same_comment_upserts_in_place(self, fresh_db: Path):
        id1 = storage.create_task(self._task("同一条评论", name="旧名"))
        id2 = storage.create_task(self._task("同一条评论", name="新名"))
        assert id1 == id2
        tasks = storage.list_tasks(type="kuaishou_comment")
        assert len(tasks) == 1
        assert tasks[0].name == "新名"

    def test_comment_whitespace_stripped_for_identity(self, fresh_db: Path):
        # 首尾空白不改变身份 —— 与 build_match_result 的 strip 口径一致。
        id1 = storage.create_task(self._task("评论A"))
        id2 = storage.create_task(self._task("  评论A  "))
        assert id1 == id2
        assert len(storage.list_tasks(type="kuaishou_comment")) == 1

    def test_update_task_recomputes_identity(self, fresh_db: Path):
        tid = storage.create_task(self._task("原评论"))
        t = storage.get_task(tid)
        assert t is not None
        t.config = {**t.config, "my_comment_text": "改后的评论"}
        storage.update_task(t)
        # 原评论的身份已释放 —— 再建同 URL+原评论应是新任务而非撞唯一索引。
        tid2 = storage.create_task(self._task("原评论"))
        assert tid2 != tid
        assert len(storage.list_tasks(type="kuaishou_comment")) == 2

    def test_blank_comment_falls_back_to_url_identity(self, fresh_db: Path):
        # 缺评论文本（坏配置）退回旧 (type, url) 身份：重复创建仍 upsert。
        id1 = storage.create_task(self._task(""))
        id2 = storage.create_task(self._task("", name="新名"))
        assert id1 == id2
        assert len(storage.list_tasks(type="kuaishou_comment")) == 1

    def test_non_comment_types_keep_url_identity(self, fresh_db: Path):
        # 知乎/百度等非评论类型：同 (type, url) 仍 upsert 合并（语义不变）。
        id1 = storage.create_task(MonitorTask(
            type="zhihu_question", name="n1",
            target_url="https://www.zhihu.com/question/1",
            config={"target_brand": "A"},
        ))
        id2 = storage.create_task(MonitorTask(
            type="zhihu_question", name="n2",
            target_url="https://www.zhihu.com/question/1",
            config={"target_brand": "B"},
        ))
        assert id1 == id2

    def test_task_dedup_key_helper(self, fresh_db: Path):
        assert storage.task_dedup_key("zhihu_question", {"target_brand": "A"}) == ""
        assert storage.task_dedup_key("kuaishou_comment", {}) == ""
        expected = hashlib.sha256("评论A".encode("utf-8")).hexdigest()
        assert storage.task_dedup_key("kuaishou_comment", {"my_comment_text": "评论A"}) == expected
        assert storage.task_dedup_key("kuaishou_comment", {"my_comment_text": " 评论A "}) == expected


# v11 时代的 monitor_tasks 形状（表级 UNIQUE + 无 dedup_key），用来构造
# 待迁移的老库。UNIQUE 子句必须与历史 DDL 逐字一致 —— 迁移用 sqlite_master
# 的 SQL 文本判断是否需要重建。
_V11_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS monitor_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    target_url TEXT NOT NULL,
    config_json TEXT NOT NULL,
    schedule_cron TEXT NOT NULL DEFAULT 'manual',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_check_at TEXT,
    last_status TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(type, target_url)
)
"""

_V11_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS monitor_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES monitor_tasks(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT -1,
    metric_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    alert_triggered INTEGER NOT NULL DEFAULT 0
)
"""


class TestV12CommentIdentityMigration:
    def test_v11_db_rebuilds_and_backfills(self, tmp_path: Path):
        db = tmp_path / "monitor.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(_V11_TASKS_DDL)
            conn.execute(_V11_RESULTS_DDL)
            conn.execute(
                "INSERT INTO monitor_tasks(id, type, name, target_url, config_json) "
                "VALUES (1, 'kuaishou_comment', 'k1', 'https://v.kuaishou.com/x', "
                "'{\"my_comment_text\": \" 老评论 \", \"top_n\": 5}')"
            )
            conn.execute(
                "INSERT INTO monitor_tasks(id, type, name, target_url, config_json) "
                "VALUES (2, 'zhihu_question', 'z1', 'https://www.zhihu.com/question/1', "
                "'{\"target_brand\": \"A\"}')"
            )
            conn.execute(
                "INSERT INTO monitor_results(task_id, checked_at, status) "
                "VALUES (1, '2026-07-01T00:00:00Z', 'ok')"
            )
            # 模拟「删过尾部 id 的任务」：seq 推到 9 后删掉该行。geo_cells /
            # geo_citations 无外键、delete_task 不清理它们，靠 AUTOINCREMENT
            # id 永不复用兜底 —— 迁移重建必须显式搬运 sqlite_sequence，否则
            # 新任务会复用 id 9 并"认领"死任务的孤儿明细。
            conn.execute(
                "INSERT INTO monitor_tasks(id, type, name, target_url, config_json) "
                "VALUES (9, 'geo_query', 'dead', 'https://example.com/geo', '{}')"
            )
            conn.execute("DELETE FROM monitor_tasks WHERE id=9")
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', '11')"
            )
            conn.commit()
        finally:
            conn.close()

        storage_mod._db_path = None
        storage_mod._initialized = False
        storage_mod._local = threading.local()
        try:
            storage.init_db(db)
            conn = storage.get_conn()

            # 表级 UNIQUE 已被重建移除，改为 (type, target_url, dedup_key) 唯一索引。
            table_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='monitor_tasks'"
            ).fetchone()[0]
            assert "UNIQUE(type, target_url)" not in table_sql
            index_names = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='monitor_tasks'"
                ).fetchall()
            }
            assert "uq_monitor_tasks_identity" in index_names
            # v6 的 (type, target_url) 查询索引在重建后补回。
            assert "idx_monitor_tasks_target_url" in index_names

            # dedup_key 回填：评论任务 = sha256(strip 后文本)；非评论 = ''。
            key1 = conn.execute("SELECT dedup_key FROM monitor_tasks WHERE id=1").fetchone()[0]
            assert key1 == hashlib.sha256("老评论".encode("utf-8")).hexdigest()
            key2 = conn.execute("SELECT dedup_key FROM monitor_tasks WHERE id=2").fetchone()[0]
            assert key2 == ""

            # 子行保留、外键完好。
            n = conn.execute(
                "SELECT COUNT(*) FROM monitor_results WHERE task_id=1"
            ).fetchone()[0]
            assert n == 1
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

            # 迁移后：同 URL 第二条评论可以独立建任务；且 AUTOINCREMENT 序号
            # 接旧库的 seq（=9）继续 —— 不复用已删任务的 id（防孤儿 geo 明细
            # 被新任务认领）。
            new_id = storage.create_task(MonitorTask(
                type="kuaishou_comment", name="k2",
                target_url="https://v.kuaishou.com/x",
                config={"my_comment_text": "新评论"},
            ))
            assert new_id > 9
            assert len(storage.list_tasks(type="kuaishou_comment")) == 2
        finally:
            c = getattr(storage_mod._local, "conn", None)
            if c is not None:
                c.close()
            storage_mod._db_path = None
            storage_mod._initialized = False

    def test_migration_idempotent_on_second_init(self, tmp_path: Path):
        db = tmp_path / "monitor.db"
        for _ in range(2):
            storage_mod._db_path = None
            storage_mod._initialized = False
            storage_mod._local = threading.local()
            try:
                storage.init_db(db)
                tid = storage.create_task(MonitorTask(
                    type="kuaishou_comment", name="k",
                    target_url="https://v.kuaishou.com/x",
                    config={"my_comment_text": "评论"},
                ))
                assert tid >= 1
            finally:
                c = getattr(storage_mod._local, "conn", None)
                if c is not None:
                    c.close()
                storage_mod._db_path = None
                storage_mod._initialized = False
