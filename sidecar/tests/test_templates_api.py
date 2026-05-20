"""Routes for comment template library — list + tags (v5 T5)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.mining import storage as mining_storage


def test_list_templates_empty(client: TestClient, monitor_db: Path):
    r = client.get("/api/mining/templates")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


def test_list_templates_with_filters(client: TestClient, monitor_db: Path):
    mining_storage.create_template(text="A 种草", tags=["种草"])
    mining_storage.create_template(text="B 对比", tags=["对比"])
    mining_storage.update_template(
        mining_storage.create_template(text="C 都有", tags=["种草", "对比"]),
        starred=True,
    )

    # No filter — 3 items, starred first
    r = client.get("/api/mining/templates")
    body = r.json()
    assert body["total"] == 3
    assert body["items"][0]["text"] == "C 都有"

    # Tag filter — intersection
    r = client.get("/api/mining/templates?tags=种草,对比")
    assert {it["text"] for it in r.json()["items"]} == {"C 都有"}

    # Search — LIKE on text column only (per storage layer)
    r = client.get("/api/mining/templates?search=对比")
    assert {it["text"] for it in r.json()["items"]} == {"B 对比"}


def test_list_used_tags(client: TestClient, monitor_db: Path):
    mining_storage.create_template(text="x", tags=["a", "b"])
    mining_storage.create_template(text="y", tags=["b", "c"])
    r = client.get("/api/mining/templates/tags")
    assert r.json() == {"tags": ["a", "b", "c"]}


def test_list_templates_strips_empty_tags(client: TestClient, monitor_db: Path):
    """?tags=,A, should be ["A"] not ["", "A", ""] (silent-failure fix)."""
    mining_storage.create_template(text="只有种草", tags=["种草"])

    # Comma garbage in tags should be ignored, not poison the filter
    r = client.get("/api/mining/templates?tags=,种草,")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # All-empty tags string treated as no filter
    r = client.get("/api/mining/templates?tags=,,")
    # Falls through to "tags=None" semantics → returns everything
    assert r.json()["total"] == 1
