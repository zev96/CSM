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


def test_create_and_get_roundtrip(xhs_db):
    did = xs.create_draft(
        title="标题",
        body="正文\n第二行",
        topics=["考证", "干货"],
        image_ids=["a", "b"],
        cover_index=1,
        theme_id="warm_yellow",
    )
    assert isinstance(did, str) and len(did) == 32  # uuid4 hex
    d = xs.get_draft(did)
    assert d is not None
    assert d["id"] == did
    assert d["title"] == "标题"
    assert d["body"] == "正文\n第二行"
    assert d["topics"] == ["考证", "干货"]
    assert d["image_ids"] == ["a", "b"]
    assert d["cover_index"] == 1
    assert d["theme_id"] == "warm_yellow"
    assert d["created_at"] and d["updated_at"]


def test_create_defaults(xhs_db):
    did = xs.create_draft()
    d = xs.get_draft(did)
    assert d["title"] == ""
    assert d["body"] == ""
    assert d["topics"] == []
    assert d["image_ids"] == []
    assert d["cover_index"] == 0
    assert d["theme_id"] is None


def test_get_missing_returns_none(xhs_db):
    assert xs.get_draft("nope") is None


def test_update_partial_and_bumps_updated_at(xhs_db):
    did = xs.create_draft(title="old", body="b")
    before = xs.get_draft(did)["updated_at"]
    updated = xs.update_draft(did, title="new", topics=["x"])
    assert updated is not None
    assert updated["title"] == "new"
    assert updated["body"] == "b"          # 未传 → 保持
    assert updated["topics"] == ["x"]
    # updated_at 单调不回退（strftime 毫秒精度；>= 足够稳，避免同毫秒 flake）
    assert updated["updated_at"] >= before


def test_update_missing_returns_none(xhs_db):
    assert xs.update_draft("nope", title="x") is None


def test_update_noop_when_no_fields(xhs_db):
    did = xs.create_draft(title="keep")
    updated = xs.update_draft(did)
    assert updated["title"] == "keep"


def test_list_orders_by_updated_at_desc(xhs_db):
    import time
    d1 = xs.create_draft(title="first")
    d2 = xs.create_draft(title="second")
    # 睡 20ms 确保 d1 的 updated_at 严格晚于 d2 的 created_at —— strftime 是
    # 毫秒精度，Windows 时钟粒度可能让连续几次写落在同一毫秒，导致
    # updated_at 打平、靠随机 uuid 的 id DESC 决定顺序而 flaky。
    time.sleep(0.02)
    xs.update_draft(d1, body="touched")  # 触碰 d1 → updated_at 变新 → 应排最前
    ids = [d["id"] for d in xs.list_drafts()]
    assert ids[0] == d1
    assert set(ids) == {d1, d2}


def test_delete(xhs_db):
    did = xs.create_draft(title="x")
    assert xs.delete_draft(did) is True
    assert xs.get_draft(did) is None
    assert xs.delete_draft(did) is False  # 已不存在
