"""Routes for video_comments CRUD (Phase 2 T5).

Covers happy paths plus the edge cases the spec calls out:
* UNIQUE(video_id, tier) → 409 (spec §6.5)
* PATCH/DELETE diff & delete orphaned image files (spec §6.6)
* 404 on missing video / comment
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import mining_images_service


def _insert_video(*, video_id: int = 1, platform: str = "bilibili") -> int:
    """Add a minimal videos row. Returns the id."""
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url) VALUES(?,?,?,?)",
        (video_id, platform, f"vid-{video_id}", f"https://example/{video_id}"),
    )
    return video_id


# ── POST + GET round trip ───────────────────────────────────────────────
def test_create_and_list_comment(client: TestClient, monitor_db: Path):
    vid = _insert_video()
    r = client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "first tier", "image_ids": ["abc"], "source": "manual"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tier"] == 1
    assert body["text"] == "first tier"
    assert body["image_ids"] == ["abc"]
    assert body["image_urls"] == ["/api/mining/images/abc"]
    assert body["source"] == "manual"
    assert body["status"] == "draft"

    # GET reflects it
    g = client.get(f"/api/mining/videos/{vid}/comments")
    assert g.status_code == 200
    items = g.json()["comments"]
    assert len(items) == 1
    assert items[0]["id"] == body["id"]


# ── tier conflict → 409 ────────────────────────────────────────────────
def test_create_same_tier_twice_returns_409(client: TestClient, monitor_db: Path):
    vid = _insert_video()
    r1 = client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "a", "image_ids": []},
    )
    assert r1.status_code == 201
    r2 = client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "b", "image_ids": []},
    )
    assert r2.status_code == 409


# ── PATCH text + image diff cleanup ────────────────────────────────────
def test_patch_text_and_image_cleanup(
    client: TestClient, monitor_db: Path, monkeypatch: pytest.MonkeyPatch,
):
    """PATCH that drops one image must call delete_images on the removed id only."""
    vid = _insert_video()
    r1 = client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "v1", "image_ids": ["keep", "drop"]},
    )
    cid = r1.json()["id"]

    seen: list[list[str]] = []
    monkeypatch.setattr(
        mining_images_service, "delete_images",
        lambda ids: seen.append(list(ids)),
    )

    r2 = client.patch(
        f"/api/mining/comments/{cid}",
        json={"text": "v2", "image_ids": ["keep"]},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["text"] == "v2"
    assert body["image_ids"] == ["keep"]
    # delete_images was invoked exactly once, with the removed image only
    assert seen == [["drop"]]


def test_patch_text_only_does_not_touch_images(
    client: TestClient, monitor_db: Path, monkeypatch: pytest.MonkeyPatch,
):
    """If image_ids is absent in the PATCH, do not call delete_images at all."""
    vid = _insert_video()
    r1 = client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "v1", "image_ids": ["a"]},
    )
    cid = r1.json()["id"]

    seen: list[list[str]] = []
    monkeypatch.setattr(
        mining_images_service, "delete_images",
        lambda ids: seen.append(list(ids)),
    )

    r2 = client.patch(f"/api/mining/comments/{cid}", json={"text": "v2"})
    assert r2.status_code == 200
    assert r2.json()["image_ids"] == ["a"]
    assert seen == []


def test_patch_missing_comment_returns_404(client: TestClient, monitor_db: Path):
    r = client.patch("/api/mining/comments/99999", json={"text": "x"})
    assert r.status_code == 404


# ── DELETE removes row + images ────────────────────────────────────────
def test_delete_comment_removes_row_and_images(
    client: TestClient, monitor_db: Path, monkeypatch: pytest.MonkeyPatch,
):
    vid = _insert_video()
    r1 = client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "x", "image_ids": ["img1", "img2"]},
    )
    cid = r1.json()["id"]

    seen: list[list[str]] = []
    monkeypatch.setattr(
        mining_images_service, "delete_images",
        lambda ids: seen.append(list(ids)),
    )

    r2 = client.delete(f"/api/mining/comments/{cid}")
    assert r2.status_code == 204
    # gone
    g = client.get(f"/api/mining/videos/{vid}/comments")
    assert g.json()["comments"] == []
    # cleanup invoked with all referenced ids
    assert seen == [["img1", "img2"]]


def test_delete_missing_returns_404(client: TestClient, monitor_db: Path):
    r = client.delete("/api/mining/comments/99999")
    assert r.status_code == 404


# ── POST with missing video → 404 ──────────────────────────────────────
def test_post_comment_for_missing_video_returns_404(
    client: TestClient, monitor_db: Path,
):
    r = client.post(
        "/api/mining/videos/99999/comments",
        json={"tier": 1, "text": "x", "image_ids": []},
    )
    assert r.status_code == 404


def test_get_comments_for_missing_video_returns_404(
    client: TestClient, monitor_db: Path,
):
    r = client.get("/api/mining/videos/99999/comments")
    assert r.status_code == 404


# ── list returns tiers in ascending order ──────────────────────────────
def test_list_comments_sorted_by_tier(client: TestClient, monitor_db: Path):
    vid = _insert_video()
    # Insert tier 2 first, then 1, to confirm sort
    client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 2, "text": "second", "image_ids": []},
    )
    client.post(
        f"/api/mining/videos/{vid}/comments",
        json={"tier": 1, "text": "first", "image_ids": []},
    )
    r = client.get(f"/api/mining/videos/{vid}/comments")
    tiers = [c["tier"] for c in r.json()["comments"]]
    assert tiers == [1, 2]
