"""mining_images_service: magic-bytes filter, size cap, path traversal."""
from pathlib import Path

import pytest

from csm_sidecar.services import mining_images_service as images
from csm_core import config as core_config


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch) -> Path:
    """Redirect default_config_dir() to a temp dir so save_image writes
    under tmp_path/mining_images instead of the real %LOCALAPPDATA%.
    """
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)
    root = images.image_root()
    return root


# ── Magic bytes ────────────────────────────────────────────────────────
# Real minimal headers — content past the magic bytes can be anything;
# save_image doesn't decode the body, it just sniffs the first 12 bytes.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 256
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 256
HTML_BYTES = b"<html><body>hi</body></html>" + b"\x00" * 256


def test_save_jpeg_round_trip(isolated_root: Path):
    image_id = images.save_image(123, JPEG_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None
    assert path.suffix == ".jpg"
    assert path.read_bytes() == JPEG_BYTES


def test_save_png_round_trip(isolated_root: Path):
    image_id = images.save_image(123, PNG_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None
    assert path.suffix == ".png"
    assert path.read_bytes() == PNG_BYTES


def test_save_webp_round_trip(isolated_root: Path):
    image_id = images.save_image(123, WEBP_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None
    assert path.suffix == ".webp"
    assert path.read_bytes() == WEBP_BYTES


def test_reject_html_payload(isolated_root: Path):
    with pytest.raises(ValueError, match="unsupported image type"):
        images.save_image(1, HTML_BYTES)


def test_reject_tiny_payload(isolated_root: Path):
    with pytest.raises(ValueError, match="unsupported image type"):
        images.save_image(1, b"\x00")


def test_reject_oversized(isolated_root: Path):
    # 5 MB + 1 byte. Prefix with PNG magic so we know the only thing
    # tripping is the size guard, not the type sniff.
    too_big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        images.save_image(1, too_big)


# ── Path-traversal guard ───────────────────────────────────────────────
def test_get_image_path_rejects_traversal(isolated_root: Path):
    assert images.get_image_path("../../etc/passwd") is None


def test_get_image_path_rejects_path_separator(isolated_root: Path):
    assert images.get_image_path("a/b") is None
    assert images.get_image_path("a\\b") is None


def test_get_image_path_empty(isolated_root: Path):
    assert images.get_image_path("") is None


def test_get_image_path_unknown_id(isolated_root: Path):
    assert images.get_image_path("deadbeef" * 4) is None


# ── delete_images ──────────────────────────────────────────────────────
def test_delete_images_removes_files(isolated_root: Path):
    image_id = images.save_image(7, PNG_BYTES)
    assert images.get_image_path(image_id) is not None
    images.delete_images([image_id])
    assert images.get_image_path(image_id) is None


def test_delete_images_missing_does_not_raise(isolated_root: Path):
    # Mix of one real + two missing.
    image_id = images.save_image(7, PNG_BYTES)
    images.delete_images([image_id, "missing-1", "missing-2"])
    assert images.get_image_path(image_id) is None


def test_delete_empty_list_noop(isolated_root: Path):
    # Should not raise even with no files.
    images.delete_images([])


# ── image_root creates dir ─────────────────────────────────────────────
def test_image_root_creates_directory(tmp_path: Path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.setattr(core_config, "default_config_dir", lambda: target)
    assert not target.exists()
    root = images.image_root()
    assert root.exists()
    assert root == target / "mining_images"
