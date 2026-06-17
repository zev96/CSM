"""Routes for xhs draft CRUD (P0 T3)。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_then_get(client: TestClient, xhs_db: Path):
    r = client.post("/api/xhs/drafts", json={"title": "T", "body": "B", "topics": ["x"]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "T"
    assert d["body"] == "B"
    assert d["topics"] == ["x"]
    assert d["id"]

    g = client.get(f"/api/xhs/drafts/{d['id']}")
    assert g.status_code == 200
    assert g.json()["id"] == d["id"]


def test_create_empty_ok(client: TestClient, xhs_db: Path):
    r = client.post("/api/xhs/drafts", json={})
    assert r.status_code == 201
    assert r.json()["title"] == ""


def test_list(client: TestClient, xhs_db: Path):
    # xhs_db fixture 每个测试一个全新 tmp 库，所以列表里只有下面新建的两条
    client.post("/api/xhs/drafts", json={"title": "a"})
    client.post("/api/xhs/drafts", json={"title": "b"})
    r = client.get("/api/xhs/drafts")
    assert r.status_code == 200
    drafts = r.json()["drafts"]
    assert len(drafts) == 2
    assert {d["title"] for d in drafts} == {"a", "b"}


def test_patch_partial(client: TestClient, xhs_db: Path):
    cid = client.post("/api/xhs/drafts", json={"title": "old", "body": "keep"}).json()["id"]
    r = client.patch(f"/api/xhs/drafts/{cid}", json={"title": "new"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "new"
    assert body["body"] == "keep"


def test_patch_missing_404(client: TestClient, xhs_db: Path):
    r = client.patch("/api/xhs/drafts/deadbeef", json={"title": "x"})
    assert r.status_code == 404


def test_get_missing_404(client: TestClient, xhs_db: Path):
    r = client.get("/api/xhs/drafts/deadbeef")
    assert r.status_code == 404


def test_delete(client: TestClient, xhs_db: Path):
    cid = client.post("/api/xhs/drafts", json={"title": "x"}).json()["id"]
    r = client.delete(f"/api/xhs/drafts/{cid}")
    assert r.status_code == 204
    assert client.get(f"/api/xhs/drafts/{cid}").status_code == 404


def test_delete_missing_404(client: TestClient, xhs_db: Path):
    assert client.delete("/api/xhs/drafts/deadbeef").status_code == 404


# ── 副本（P4 T14）────────────────────────────────────────────────────────────

def test_duplicate_draft_copies_fields_and_images(client: TestClient, xhs_db: Path, tmp_path, monkeypatch):
    from csm_core import config as core_config
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)

    d = client.post("/api/xhs/drafts", json={"title": "原标题", "body": "正文", "topics": ["a"]}).json()
    did = d["id"]
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    up = client.post(f"/api/xhs/drafts/{did}/images", files={"file": ("x.jpg", jpeg, "image/jpeg")}).json()
    client.patch(f"/api/xhs/drafts/{did}", json={"image_ids": [up["image_id"]], "cover_index": 0})

    r = client.post(f"/api/xhs/drafts/{did}/duplicate")
    assert r.status_code == 201
    dup = r.json()
    assert dup["id"] != did
    assert dup["title"] == "原标题（副本）"
    assert dup["body"] == "正文"
    assert dup["topics"] == ["a"]
    assert len(dup["image_ids"]) == 1
    assert dup["image_ids"][0] != up["image_id"]  # 新 id


def test_duplicate_missing_draft_404(client: TestClient, xhs_db: Path):
    assert client.post("/api/xhs/drafts/nope/duplicate").status_code == 404
