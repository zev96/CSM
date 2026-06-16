"""Direct unit tests for csm_core/xhs/storage.py（独立 xhs.db）。"""
from __future__ import annotations

from csm_core.xhs import storage as xs


def test_init_creates_schema(xhs_db):
    conn = xs.get_conn()
    # schema_meta 记录版本
    row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    assert row is not None
    assert int(row[0]) == xs._SCHEMA_VERSION
    # xhs_drafts 表存在且列齐
    cols = {r[1] for r in conn.execute("PRAGMA table_info(xhs_drafts)").fetchall()}
    assert cols == {
        "id", "title", "body", "topics_json", "image_ids_json",
        "cover_index", "theme_id", "created_at", "updated_at",
    }


def test_init_is_idempotent(xhs_db):
    # 同路径再 init 不抛
    xs.init_db(xhs_db)
    # 不同路径再 init 应拒绝
    import pytest
    with pytest.raises(RuntimeError):
        xs.init_db(xhs_db.parent / "other.db")
