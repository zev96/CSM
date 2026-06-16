"""Routes for xhs image upload + serve + cascade cleanup (P2 T2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core import config as core_config
from csm_sidecar.services import xhs_images_service as images

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 256
HTML_BYTES = b"<html><body>nope</body></html>" + b"\x00" * 256


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect image storage to tmp_path so we don't touch %LOCALAPPDATA%."""
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)
    return images.image_root()


def _new_draft(client: TestClient) -> str:
    r = client.post("/api/xhs/drafts", json={"title": "T"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_upload_png_returns_id_and_url(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    r = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["image_id"]
    assert body["url"] == f"/api/xhs/images/{body['image_id']}"
    assert body["size"] == len(PNG_BYTES)


def test_get_image_returns_bytes_and_content_type(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    image_id = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    ).json()["image_id"]
    g = client.get(f"/api/xhs/images/{image_id}")
    assert g.status_code == 200
    assert g.headers["content-type"].startswith("image/png")
    assert g.content == PNG_BYTES


def test_get_image_jpeg_content_type(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    image_id = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")},
    ).json()["image_id"]
    g = client.get(f"/api/xhs/images/{image_id}")
    assert g.status_code == 200
    assert g.headers["content-type"].startswith("image/jpeg")


def test_get_missing_image_returns_404(client: TestClient, xhs_db: Path, isolated_root: Path):
    assert client.get("/api/xhs/images/" + "deadbeef" * 4).status_code == 404


def test_upload_html_payload_returns_400(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    r = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("evil.png", HTML_BYTES, "image/png")},
    )
    assert r.status_code == 400
    assert "unsupported" in r.text.lower()


def test_upload_oversized_returns_400(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    too_big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
    r = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("big.png", too_big, "image/png")},
    )
    assert r.status_code == 400
    assert "too large" in r.text.lower()


def test_upload_for_missing_draft_returns_404(client: TestClient, xhs_db: Path, isolated_root: Path):
    r = client.post(
        "/api/xhs/drafts/nonexistent/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 404


def test_delete_draft_cascades_images(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    image_id = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    ).json()["image_id"]
    assert client.get(f"/api/xhs/images/{image_id}").status_code == 200
    assert client.delete(f"/api/xhs/drafts/{did}").status_code == 204
    # 文件随草稿级联删除
    assert client.get(f"/api/xhs/images/{image_id}").status_code == 404


def test_patch_removing_image_deletes_file(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    a = client.post(f"/api/xhs/drafts/{did}/images", files={"file": ("a.png", PNG_BYTES, "image/png")}).json()["image_id"]
    b = client.post(f"/api/xhs/drafts/{did}/images", files={"file": ("b.png", PNG_BYTES, "image/png")}).json()["image_id"]
    # 先把两张都挂到草稿
    client.patch(f"/api/xhs/drafts/{did}", json={"image_ids": [a, b]})
    # 再 PATCH 成只留 b → a 的文件应被删
    r = client.patch(f"/api/xhs/drafts/{did}", json={"image_ids": [b]})
    assert r.status_code == 200
    assert client.get(f"/api/xhs/images/{a}").status_code == 404
    assert client.get(f"/api/xhs/images/{b}").status_code == 200
