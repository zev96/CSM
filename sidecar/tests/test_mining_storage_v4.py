"""Schema v4 migration + comment-storage helpers (Outreach Phase 2/3).

Three migration scenarios covered:
1. Fresh DB jumps v0 → v4 in one init_db() call
2. A pre-existing v3-shaped DB (no video_comments, no ai_summary) upgrades
   to v4 cleanly without losing rows
3. Re-running apply_v4_migration on an already-v4 DB is a no-op
"""
import sqlite3
import threading
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch):
    """Reset monitor_storage globals and point at a tmp_path DB."""
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    monkeypatch.setattr(monitor_storage, "_local", threading.local())
    db = tmp_path / "monitor.db"
    monitor_storage.init_db(db)
    yield db
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def _video_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()}


# ── Fresh-DB scenarios ────────────────────────────────────────────────
def test_fresh_db_has_video_comments_and_ai_summary(fresh_db: Path):
    tables = _table_names(fresh_db)
    assert "video_comments" in tables
    cols = _video_columns(fresh_db)
    assert "ai_summary" in cols


def test_schema_version_is_4(fresh_db: Path):
    with sqlite3.connect(str(fresh_db)) as conn:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
    assert row[0] == "4"


def test_video_comments_index_present(fresh_db: Path):
    with sqlite3.connect(str(fresh_db)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_video_comments_video'"
        ).fetchall()
    assert len(rows) == 1


# ── v3 → v4 upgrade preserves data ────────────────────────────────────
def test_v3_to_v4_upgrade_preserves_video_rows(tmp_path: Path, monkeypatch):
    """Simulate a pre-v4 DB by hand-running v1+v3 DDL, then let init_db
    upgrade it and verify no rows were lost and the new shape is in place.
    """
    db = tmp_path / "monitor.db"
    # Hand-build a v3 DB: run _DDL_V1 + v3 mining DDL only, then close.
    conn = sqlite3.connect(str(db))
    try:
        for stmt in monitor_storage._DDL_V1:
            conn.execute(stmt)
        ms.apply_v3_migration(conn)
        # Insert one video row so we can verify it survives the upgrade.
        conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title) "
            "VALUES('douyin', 'preexisting', 'http://x/1', 'kept')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version','3')"
        )
        conn.commit()
    finally:
        conn.close()

    # Sanity: pre-upgrade shape has no ai_summary and no video_comments.
    assert "ai_summary" not in _video_columns(db)
    assert "video_comments" not in _table_names(db)

    # Now run init_db to upgrade.
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    monkeypatch.setattr(monitor_storage, "_local", threading.local())
    monitor_storage.init_db(db)

    # Post-upgrade: row preserved + new shape applied + version bumped.
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute("SELECT title FROM videos").fetchall()
        assert rows == [("kept",)]
        ver = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0]
    assert ver == "4"
    assert "ai_summary" in _video_columns(db)
    assert "video_comments" in _table_names(db)


def test_apply_v4_migration_is_idempotent(fresh_db: Path):
    """Running apply_v4_migration twice on a v4 DB must not raise."""
    with sqlite3.connect(str(fresh_db)) as conn:
        # Should be a no-op now (CREATE IF NOT EXISTS + PRAGMA-guarded ALTER).
        ms.apply_v4_migration(conn)
        ms.apply_v4_migration(conn)
    # Still only one ai_summary column.
    cols = [
        c for c in _video_columns(fresh_db) if c == "ai_summary"
    ]
    assert cols == ["ai_summary"]


# ── UNIQUE(video_id, tier) ────────────────────────────────────────────
def test_video_comments_unique_video_tier(fresh_db: Path):
    monkeypatch_conn = monitor_storage.get_conn()
    monkeypatch_conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','x','u')"
    )
    vid = monkeypatch_conn.execute(
        "SELECT id FROM videos WHERE platform_video_id='x'"
    ).fetchone()[0]
    ms.create_comment(vid, tier=1, text="first")
    with pytest.raises(sqlite3.IntegrityError):
        ms.create_comment(vid, tier=1, text="dup")


# ── next_tier ─────────────────────────────────────────────────────────
def _make_video(monitor_conn) -> int:
    cur = monitor_conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin', ?, 'u') RETURNING id",
        (f"vid-{Path(__file__).stem}-{id(monitor_conn)}",),
    )
    return int(cur.fetchone()[0])


def test_next_tier_empty_is_1(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    assert ms.next_tier(vid) == 1


def test_next_tier_after_first_insert_is_2(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    ms.create_comment(vid, tier=1, text="first")
    assert ms.next_tier(vid) == 2


# ── list / update / delete comments ───────────────────────────────────
def test_list_comments_orders_by_tier(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    ms.create_comment(vid, tier=2, text="second", image_ids=["a", "b"])
    ms.create_comment(vid, tier=1, text="first", image_ids=["c"])
    rows = ms.list_comments(vid)
    assert [r["tier"] for r in rows] == [1, 2]
    assert rows[0]["image_ids"] == ["c"]
    assert rows[0]["image_urls"] == ["/api/mining/images/c"]
    assert rows[1]["image_urls"] == ["/api/mining/images/a", "/api/mining/images/b"]


def test_update_comment_text_and_images(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    cid = ms.create_comment(vid, tier=1, text="orig", image_ids=["x"])
    updated = ms.update_comment(cid, text="new", image_ids=["y", "z"])
    assert updated is not None
    assert updated["text"] == "new"
    assert updated["image_ids"] == ["y", "z"]


def test_update_comment_missing_returns_none(fresh_db: Path):
    assert ms.update_comment(99999, text="x") is None


def test_delete_comment(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    cid = ms.create_comment(vid, tier=1, text="x")
    assert ms.delete_comment(cid) is True
    assert ms.list_comments(vid) == []


# ── ai_summary + bulk_mark_commented ──────────────────────────────────
def test_set_ai_summary_round_trips(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    ms.set_ai_summary(vid, "hello summary")
    row = conn.execute("SELECT ai_summary FROM videos WHERE id=?", (vid,)).fetchone()
    assert row["ai_summary"] == "hello summary"


def test_list_videos_includes_ai_summary(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    ms.set_ai_summary(vid, "the summary")
    rows, _ = ms.list_videos(commented="all")
    assert rows[0]["ai_summary"] == "the summary"


def test_bulk_mark_commented_flips_rows(fresh_db: Path):
    conn = monitor_storage.get_conn()
    v1 = _make_video(conn)
    # Insert two more videos with distinct unique keys.
    cur = conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','aa','u') RETURNING id"
    )
    v2 = int(cur.fetchone()[0])
    cur = conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','bb','u') RETURNING id"
    )
    v3 = int(cur.fetchone()[0])

    n = ms.bulk_mark_commented([v1, v2], True)
    assert n == 2
    rows = conn.execute(
        "SELECT id, already_commented, commented_source FROM videos ORDER BY id"
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    assert by_id[v1]["already_commented"] == 1
    assert by_id[v1]["commented_source"] == "manual"
    assert by_id[v2]["already_commented"] == 1
    assert by_id[v3]["already_commented"] == 0


def test_bulk_mark_commented_empty_list_returns_zero(fresh_db: Path):
    assert ms.bulk_mark_commented([], True) == 0


def test_bulk_mark_uncommented_clears_metadata(fresh_db: Path):
    conn = monitor_storage.get_conn()
    vid = _make_video(conn)
    ms.bulk_mark_commented([vid], True)
    ms.bulk_mark_commented([vid], False)
    row = conn.execute(
        "SELECT already_commented, commented_source, commented_at FROM videos WHERE id=?",
        (vid,),
    ).fetchone()
    assert row["already_commented"] == 0
    assert row["commented_source"] is None
    assert row["commented_at"] is None
