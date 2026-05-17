"""Routes for image upload + serve (Phase 2 T5).

Covers the multipart upload happy path, magic-bytes rejection, size cap,
and the static GET handler (404 + content-type sniffing).

The isolated_root fixture redirects ``default_config_dir`` to tmp so we
never touch the user's real %LOCALAPPDATA%/mining_images.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core import config as core_config
from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import mining_images_service as images

# 1x1 PNG header + minimal IHDR; full bytes don't matter past magic.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 256
HTML_BYTES = b"<html><body>nope</body></html>" + b"\x00" * 256


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect image storage to tmp_path so we don't touch %LOCALAPPDATA%."""
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)
    return images.image_root()


def _insert_video(*, video_id: int = 1) -> int:
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url) VALUES(?,?,?,?)",
        (video_id, "bilibili", f"v-{video_id}", f"https://example/{video_id}"),
    )
    return video_id


# ── Upload happy path ──────────────────────────────────────────────────
def test_upload_png_returns_id_and_url(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    vid = _insert_video()
    r = client.post(
        "/api/mining/comments/images",
        data={"video_id": str(vid)},
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["image_id"]
    assert body["url"] == f"/api/mining/images/{body['image_id']}"
    assert body["size"] == len(PNG_BYTES)


# ── GET round trip ─────────────────────────────────────────────────────
def test_get_image_returns_bytes_and_content_type(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    vid = _insert_video()
    r = client.post(
        "/api/mining/comments/images",
        data={"video_id": str(vid)},
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    image_id = r.json()["image_id"]

    g = client.get(f"/api/mining/images/{image_id}")
    assert g.status_code == 200
    assert g.headers["content-type"].startswith("image/png")
    assert g.content == PNG_BYTES


def test_get_image_jpeg_content_type(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    vid = _insert_video()
    r = client.post(
        "/api/mining/comments/images",
        data={"video_id": str(vid)},
        files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")},
    )
    image_id = r.json()["image_id"]
    g = client.get(f"/api/mining/images/{image_id}")
    assert g.status_code == 200
    assert g.headers["content-type"].startswith("image/jpeg")


# ── 404 on missing id ──────────────────────────────────────────────────
def test_get_missing_image_returns_404(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    r = client.get("/api/mining/images/deadbeef" * 4)
    assert r.status_code == 404


# ── Reject .html bytes (magic-bytes mismatch) ──────────────────────────
def test_upload_html_payload_returns_400(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    vid = _insert_video()
    r = client.post(
        "/api/mining/comments/images",
        data={"video_id": str(vid)},
        # Even with image/png Content-Type, the magic-bytes sniff rejects
        # the body — defends against XSS via a .html being served as png.
        files={"file": ("evil.png", HTML_BYTES, "image/png")},
    )
    assert r.status_code == 400
    assert "unsupported" in r.text.lower()


# ── Reject >5MB ────────────────────────────────────────────────────────
def test_upload_oversized_returns_400(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    vid = _insert_video()
    too_big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
    r = client.post(
        "/api/mining/comments/images",
        data={"video_id": str(vid)},
        files={"file": ("big.png", too_big, "image/png")},
    )
    assert r.status_code == 400
    assert "too large" in r.text.lower()


# ── Upload for missing video → 404 ─────────────────────────────────────
def test_upload_for_missing_video_returns_404(
    client: TestClient, monitor_db: Path, isolated_root: Path,
):
    r = client.post(
        "/api/mining/comments/images",
        data={"video_id": "99999"},
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 404
