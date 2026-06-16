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
