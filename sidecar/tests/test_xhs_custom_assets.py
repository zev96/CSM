"""xhs_custom_assets DAO（Task 1）+ 路由（Task 2）测试。"""
from __future__ import annotations

import threading

import pytest

from csm_core.xhs import storage


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_db_path", None, raising=True)
    monkeypatch.setattr(storage, "_initialized", False, raising=True)
    monkeypatch.setattr(storage, "_local", threading.local(), raising=True)
    storage.init_db(tmp_path / "xhs.db")
    yield storage


def test_create_and_list_custom_asset(db):
    asset = db.create_custom_asset(kind="copy", payload={"text": "今天也要元气满满"})
    assert asset["id"]
    assert asset["kind"] == "copy"
    assert asset["payload"] == {"text": "今天也要元气满满"}
    assert asset["created_at"]

    rows = db.list_custom_assets()
    assert len(rows) == 1
    assert rows[0]["id"] == asset["id"]


def test_list_filters_by_kind(db):
    db.create_custom_asset(kind="copy", payload={"text": "a"})
    db.create_custom_asset(kind="template", payload={"name": "n", "title": "t", "body": "b", "topics": []})
    assert len(db.list_custom_assets(kind="copy")) == 1
    assert len(db.list_custom_assets(kind="template")) == 1
    assert len(db.list_custom_assets()) == 2


def test_payload_roundtrips_complex_shape(db):
    payload = {"name": "我的话题", "tags": ["秋冬穿搭", "通勤", "显瘦"]}
    a = db.create_custom_asset(kind="topic_group", payload=payload)
    got = db.list_custom_assets(kind="topic_group")[0]
    assert got["payload"] == payload
    assert a["payload"]["tags"][0] == "秋冬穿搭"


def test_delete_custom_asset(db):
    a = db.create_custom_asset(kind="copy", payload={"text": "x"})
    assert db.delete_custom_asset(a["id"]) is True
    assert db.list_custom_assets() == []
    assert db.delete_custom_asset(a["id"]) is False


def test_list_order_newest_first(db):
    a = db.create_custom_asset(kind="copy", payload={"text": "first"})
    b = db.create_custom_asset(kind="copy", payload={"text": "second"})
    rows = db.list_custom_assets(kind="copy")
    assert rows[0]["id"] == b["id"]
    assert rows[1]["id"] == a["id"]
