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


def test_create_template(client: TestClient, monitor_db: Path):
    r = client.post("/api/mining/templates", json={"text": "新建模板", "tags": ["种草"]})
    assert r.status_code == 201
    body = r.json()
    assert body["template"]["text"] == "新建模板"
    assert body["template"]["tags"] == ["种草"]


def test_create_template_duplicate_returns_409(client: TestClient, monitor_db: Path):
    r1 = client.post("/api/mining/templates", json={"text": "dup"})
    assert r1.status_code == 201
    existing_id = r1.json()["template"]["id"]
    r2 = client.post("/api/mining/templates", json={"text": "dup"})
    assert r2.status_code == 409
    assert r2.json() == {"detail": "duplicate", "existing_id": existing_id}


def test_create_template_too_long_returns_400(client: TestClient, monitor_db: Path):
    r = client.post("/api/mining/templates", json={"text": "x" * 2001})
    assert r.status_code == 400
    assert r.json()["detail"] == "text_too_long"


def test_create_template_too_many_tags(client: TestClient, monitor_db: Path):
    r = client.post("/api/mining/templates", json={"text": "ok", "tags": ["t"] * 11})
    assert r.status_code == 400
    assert r.json()["detail"] == "too_many_tags"


def test_create_template_tag_too_long(client: TestClient, monitor_db: Path):
    """A single tag longer than 12 chars should return 400 tag_too_long."""
    r = client.post("/api/mining/templates", json={"text": "ok", "tags": ["x" * 13]})
    assert r.status_code == 400
    assert r.json()["detail"] == "tag_too_long"


def test_patch_template(client: TestClient, monitor_db: Path):
    tid = mining_storage.create_template(text="原")
    r = client.patch(f"/api/mining/templates/{tid}", json={"starred": True, "text": "新"})
    assert r.status_code == 200
    assert r.json()["template"]["starred"] is True
    assert r.json()["template"]["text"] == "新"


def test_delete_template(client: TestClient, monitor_db: Path):
    tid = mining_storage.create_template(text="删")
    r = client.delete(f"/api/mining/templates/{tid}")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    r2 = client.delete(f"/api/mining/templates/{tid}")
    assert r2.status_code == 404


def test_use_bumps_count_and_returns_text(client: TestClient, monitor_db: Path):
    tid = mining_storage.create_template(text="复用我")
    r = client.post(f"/api/mining/templates/{tid}/use")
    assert r.status_code == 200
    assert r.json() == {"text": "复用我"}
    # Confirm DB
    from csm_core.monitor.storage import get_conn
    row = get_conn().execute("SELECT use_count FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row[0] == 1


def test_bulk_import(client, monitor_db):
    r = client.post(
        "/api/mining/templates/bulk-import",
        json={"texts": ["A", "B", "C"], "tags": ["导入"], "source_platform": "manual"},
    )
    assert r.status_code == 200
    assert r.json() == {"created": 3, "skipped_duplicates": 0}

    # 再来一次 — 全部重复
    r2 = client.post(
        "/api/mining/templates/bulk-import",
        json={"texts": ["A", "B"]},
    )
    assert r2.json() == {"created": 0, "skipped_duplicates": 2}


def test_bulk_import_too_many_returns_400(client, monitor_db):
    r = client.post(
        "/api/mining/templates/bulk-import",
        json={"texts": [f"item-{i}" for i in range(501)]},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "max_batch_exceeded"
