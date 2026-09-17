"""Schema v5 migration test — comment_templates table.

T1 of the comment-template-library plan. Three concerns:
  1. Fresh DB v0 → v5 creates the comment_templates table with the
     expected columns.
  2. apply_v5_migration is idempotent (CREATE ... IF NOT EXISTS).
  3. The two expected indexes (starred_last, hidden) exist.

The conn fixture resets monitor_storage module globals via monkeypatch
so each test gets a clean per-tmp_path DB (same pattern as
sidecar/tests/test_mining_storage_v4.py).
"""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from csm_core.monitor import storage as monitor_storage
from csm_core.mining import storage as mining_storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    # Reset module-level singletons so each test gets a fresh DB; without
    # this, the second test would hit the "already initialized" guard.
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(str(db))
    return monitor_storage.get_conn()


def test_v5_creates_templates_table(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comment_templates)").fetchall()}
    assert {
        "id", "text", "text_hash", "tags_json", "source_platform",
        "source_comment_id", "starred", "hidden", "use_count",
        "first_seen_at", "last_used_at",
    } <= cols


def test_v5_migration_idempotent(conn):
    # Re-run apply_v5_migration on already-migrated DB — should not raise.
    # (Backfill may have populated rows from prior done comments, but
    # re-running must not double them.)
    n_before = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    mining_storage.apply_v5_migration(conn)
    n_after = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_after == n_before  # idempotent


def test_v5_indexes_exist(conn):
    idx = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='comment_templates'"
    ).fetchall()}
    assert "idx_templates_starred_last" in idx
    assert "idx_templates_hidden" in idx


from csm_core.mining.storage import (
    _normalize_text, _hash_text, _upsert_template_from_comment,
)


def test_normalize_strips_and_lowers():
    assert _normalize_text("  Hello World  ") == "hello world"
    assert _normalize_text("很赞！") == "很赞！"  # 中文 + 标点保留
    assert _normalize_text("test\n") == "test"


def test_hash_is_deterministic():
    assert _hash_text("hello") == _hash_text("HELLO")
    assert _hash_text("hello") == _hash_text("  hello  ")
    assert _hash_text("hello") != _hash_text("hello!")


def test_upsert_inserts_new_template(conn):
    # Create a video + comment so source_comment_id is valid
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','vid1','http://x')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '吸力够大', 'done')")
    comment_row = dict(conn.execute(
        "SELECT id, video_id, text FROM video_comments WHERE id=1"
    ).fetchone())

    _upsert_template_from_comment(conn, comment_row)

    row = conn.execute("SELECT text, text_hash, source_platform, source_comment_id, use_count FROM comment_templates").fetchone()
    assert row["text"] == "吸力够大"
    assert row["text_hash"] == _hash_text("吸力够大")
    assert row["source_platform"] == "kuaishou"
    assert row["source_comment_id"] == 1
    assert row["use_count"] == 1


def test_upsert_second_time_bumps_use_count(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','vid1','http://x')")
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','vid2','http://y')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '吸力够大', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(2, 1, '吸力够大', 'done')")
    c1 = dict(conn.execute("SELECT id, video_id, text FROM video_comments WHERE id=1").fetchone())
    c2 = dict(conn.execute("SELECT id, video_id, text FROM video_comments WHERE id=2").fetchone())

    _upsert_template_from_comment(conn, c1)
    _upsert_template_from_comment(conn, c2)

    rows = conn.execute("SELECT COUNT(*), MAX(use_count), MIN(source_comment_id) FROM comment_templates").fetchone()
    assert rows[0] == 1                  # only 1 row (dedup)
    assert rows[1] == 2                  # use_count bumped
    assert rows[2] == 1                  # source_comment_id stays at first


# ── T3: backfill + update_comment hook ─────────────────────────────────


def test_backfill_inserts_existing_done_comments(tmp_path, monkeypatch):
    """Seed v4-style data, then trigger backfill, assert templates created."""
    db = tmp_path / "back.db"
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=False)
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=False)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=False)
    monitor_storage.init_db(str(db))
    conn = monitor_storage.get_conn()
    # Seed 3 done comments + 1 draft (draft should NOT be backfilled)
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'A', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 2, 'B', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 3, 'C', 'draft')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 4, 'A', 'done')")  # dup of 'A'
    # Wipe templates table to simulate "before backfill"
    conn.execute("DELETE FROM comment_templates")

    mining_storage._backfill_v5_templates(conn)

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 2  # 'A' + 'B' (C is draft, second 'A' deduped)
    uc = conn.execute("SELECT use_count FROM comment_templates WHERE text='A'").fetchone()[0]
    assert uc == 2  # 'A' got hit twice


def test_update_comment_draft_to_done_triggers_upsert(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '新评论', 'draft')")

    n_before = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_before == 0

    mining_storage.update_comment(1, status="done")

    n_after = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_after == 1
    row = conn.execute("SELECT text, source_platform FROM comment_templates").fetchone()
    assert row["text"] == "新评论"
    assert row["source_platform"] == "douyin"


def test_update_comment_status_unchanged_no_trigger(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'X', 'done')")
    conn.execute("DELETE FROM comment_templates")

    mining_storage.update_comment(1, text="X (edited)")  # status not changed (still 'done')

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 0  # no trigger — only draft→done triggers


def test_update_comment_done_to_draft_no_trigger(conn):
    """Reversing done → draft must not create new templates (spec §5)."""
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'X', 'done')")
    conn.execute("DELETE FROM comment_templates")

    mining_storage.update_comment(1, status="draft")

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 0


def test_apply_v5_migration_backfill_runs_once(tmp_path, monkeypatch):
    """apply_v5_migration should run backfill exactly once across calls.

    Regression test for the T3 follow-up gate: ``_migrate`` re-runs every
    migration on every ``init_db()`` (i.e. every app launch). Without the
    schema_meta marker, every done comment's ``use_count`` would be bumped
    +1 per startup — inflating the chips top-5 sort. The fix uses a
    ``templates_v5_backfilled`` marker row to short-circuit the backfill
    after first run.
    """
    db = tmp_path / "gate.db"
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=False)
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=False)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=False)
    monitor_storage.init_db(str(db))
    conn = monitor_storage.get_conn()
    # Seed a done comment AFTER the initial migration (so the marker was
    # set without seeing this row). If the gate works, calling
    # apply_v5_migration again must NOT pick up this row.
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'X', 'done')")

    mining_storage.apply_v5_migration(conn)

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 0  # backfill gated; no template created from the post-migration row

    # Also: the marker row exists (set on first init_db).
    marker = conn.execute(
        "SELECT value FROM schema_meta WHERE key='templates_v5_backfilled'"
    ).fetchone()
    assert marker is not None

    # Mutation: remove the marker, prove ungated re-run DOES backfill.
    # This proves the gate is what was blocking — not some unrelated coincidence.
    conn.execute("DELETE FROM schema_meta WHERE key='templates_v5_backfilled'")
    mining_storage.apply_v5_migration(conn)
    n2 = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n2 == 1, "ungated re-run should backfill the seeded done comment"
    # And marker re-instated
    marker2 = conn.execute(
        "SELECT value FROM schema_meta WHERE key='templates_v5_backfilled'"
    ).fetchone()
    assert marker2 is not None


# ── T4: public template DAO surface ──────────────────────────────────────


def test_create_template_manual(conn):
    tid = mining_storage.create_template(
        text="手动新建一条", tags=["种草", "测试"], source_platform=None,
    )
    row = conn.execute("SELECT * FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["text"] == "手动新建一条"
    assert json.loads(row["tags_json"]) == ["种草", "测试"]
    assert row["source_platform"] is None
    assert row["use_count"] == 0


def test_create_template_duplicate_raises(conn):
    mining_storage.create_template(text="重复条目")
    with pytest.raises(mining_storage.TemplateDuplicateError) as exc:
        mining_storage.create_template(text="重复条目")
    assert exc.value.existing_id > 0


def test_update_template_partial(conn):
    tid = mining_storage.create_template(text="原文本", tags=["a"])
    mining_storage.update_template(tid, text="新文本", starred=True)
    row = conn.execute("SELECT text, starred, hidden FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["text"] == "新文本"
    assert row["starred"] == 1
    assert row["hidden"] == 0


def test_delete_template(conn):
    tid = mining_storage.create_template(text="删我")
    assert mining_storage.delete_template(tid) is True
    assert mining_storage.delete_template(tid) is False  # already gone


def test_list_templates_filters_and_orders(conn):
    a = mining_storage.create_template(text="A 种草", tags=["种草"])
    b = mining_storage.create_template(text="B 对比", tags=["对比"])
    c = mining_storage.create_template(text="C 种草对比", tags=["种草", "对比"])
    mining_storage.update_template(b, starred=True)

    res = mining_storage.list_templates(limit=10, offset=0)
    assert res["total"] == 3
    # starred first
    assert res["items"][0]["id"] == b

    res = mining_storage.list_templates(tags=["种草", "对比"])
    assert {r["id"] for r in res["items"]} == {c}  # 取交集

    res = mining_storage.list_templates(search="种草")
    assert {r["id"] for r in res["items"]} == {a, c}

    # M4 strengthening: also verify the secondary sort keys
    # Bump c's use_count twice, leave a un-bumped — c should now sort
    # above a (use_count tiebreaker since last_used_at also advanced).
    mining_storage.bump_template_use(c)
    mining_storage.bump_template_use(c)
    res = mining_storage.list_templates(limit=10, offset=0)
    # Expected order: B (starred=True), then C (use_count=2, recent last_used_at), then A
    ids = [r["id"] for r in res["items"]]
    assert ids == [b, c, a], f"expected [b={b}, c={c}, a={a}], got {ids}"


def test_list_templates_search_escapes_wildcards(conn):
    """User typing % or _ in search should not act as SQL wildcards (M2 fix)."""
    mining_storage.create_template(text="50% off here")
    mining_storage.create_template(text="normal text")
    mining_storage.create_template(text="user_name lookup")

    # `%` should be literal, not wildcard
    res = mining_storage.list_templates(search="%")
    assert res["total"] == 1
    assert "50%" in res["items"][0]["text"]

    # `_` should be literal
    res = mining_storage.list_templates(search="_")
    assert res["total"] == 1
    assert "user_name" in res["items"][0]["text"]

    # Normal text still works
    res = mining_storage.list_templates(search="normal")
    assert res["total"] == 1


def test_bump_use(conn):
    tid = mining_storage.create_template(text="复用我")
    text = mining_storage.bump_template_use(tid)
    assert text == "复用我"
    row = conn.execute("SELECT use_count FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["use_count"] == 1
    mining_storage.bump_template_use(tid)
    row = conn.execute("SELECT use_count FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["use_count"] == 2


def test_bulk_import_with_dedup(conn):
    mining_storage.create_template(text="已存在 1")
    res = mining_storage.bulk_import_templates(
        texts=["新条目 1", "新条目 2", "已存在 1", "新条目 1"],
        tags=["导入"],
        source_platform="manual",
    )
    assert res["created"] == 2  # "新条目 1" / "新条目 2"
    assert res["skipped_duplicates"] == 2  # "已存在 1" (db) + "新条目 1" (dupe in batch)


def test_list_used_tags(conn):
    mining_storage.create_template(text="x", tags=["a", "b"])
    mining_storage.create_template(text="y", tags=["b", "c"])
    tags = mining_storage.list_used_tags()
    assert tags == ["a", "b", "c"]  # dedup + sorted
