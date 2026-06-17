"""xhs_images_service: magic-bytes filter, size cap, path traversal, cascade."""
from pathlib import Path

import pytest

from csm_sidecar.services import xhs_images_service as images
from csm_core import config as core_config


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch) -> Path:
    """Redirect default_config_dir() to a temp dir so save_image writes
    under tmp_path/xhs_images instead of the real %LOCALAPPDATA%."""
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)
    return images.image_root()


# Real minimal headers — body past the magic bytes can be anything.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 256
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 256
HTML_BYTES = b"<html><body>hi</body></html>" + b"\x00" * 256


def test_save_jpeg_round_trip(isolated_root: Path):
    image_id = images.save_image("draftA", JPEG_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None
    assert path.suffix == ".jpg"
    assert path.read_bytes() == JPEG_BYTES


def test_save_png_round_trip(isolated_root: Path):
    image_id = images.save_image("draftA", PNG_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None and path.suffix == ".png"
    assert path.read_bytes() == PNG_BYTES


def test_save_webp_round_trip(isolated_root: Path):
    image_id = images.save_image("draftA", WEBP_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None and path.suffix == ".webp"


def test_reject_html_payload(isolated_root: Path):
    with pytest.raises(ValueError, match="unsupported image type"):
        images.save_image("d", HTML_BYTES)


def test_reject_tiny_payload(isolated_root: Path):
    with pytest.raises(ValueError, match="unsupported image type"):
        images.save_image("d", b"\x00")


def test_reject_oversized(isolated_root: Path):
    too_big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        images.save_image("d", too_big)


def test_save_image_rejects_traversal_draft_id(isolated_root: Path):
    for bad in ["../escape", "a/b", "a\\b", "..", ""]:
        with pytest.raises(ValueError, match="invalid draft_id"):
            images.save_image(bad, PNG_BYTES)


def test_get_image_path_rejects_traversal(isolated_root: Path):
    assert images.get_image_path("../../etc/passwd") is None


def test_get_image_path_rejects_path_separator(isolated_root: Path):
    assert images.get_image_path("a/b") is None
    assert images.get_image_path("a\\b") is None


def test_get_image_path_empty(isolated_root: Path):
    assert images.get_image_path("") is None


def test_get_image_path_unknown_id(isolated_root: Path):
    assert images.get_image_path("deadbeef" * 4) is None


def test_delete_images_removes_files(isolated_root: Path):
    image_id = images.save_image("d7", PNG_BYTES)
    assert images.get_image_path(image_id) is not None
    images.delete_images([image_id])
    assert images.get_image_path(image_id) is None


def test_delete_images_missing_does_not_raise(isolated_root: Path):
    image_id = images.save_image("d7", PNG_BYTES)
    images.delete_images([image_id, "missing-1", "missing-2"])
    assert images.get_image_path(image_id) is None


def test_delete_empty_list_noop(isolated_root: Path):
    images.delete_images([])


def test_image_root_creates_directory(tmp_path: Path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.setattr(core_config, "default_config_dir", lambda: target)
    assert not target.exists()
    root = images.image_root()
    assert root.exists()
    assert root == target / "xhs_images"


def test_delete_draft_images_removes_whole_dir(isolated_root: Path):
    a = images.save_image("draftX", PNG_BYTES)
    b = images.save_image("draftX", JPEG_BYTES)
    assert images.get_image_path(a) is not None
    assert images.get_image_path(b) is not None
    images.delete_draft_images("draftX")
    assert images.get_image_path(a) is None
    assert images.get_image_path(b) is None
    assert not (isolated_root / "draftX").exists()


def test_delete_draft_images_rejects_traversal(isolated_root: Path):
    # Must never rmtree outside the image root.
    victim = isolated_root.parent / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x")
    images.delete_draft_images("../victim")
    assert victim.exists()  # untouched


def test_delete_draft_images_missing_noop(isolated_root: Path):
    images.delete_draft_images("never-existed")  # no raise


# ── copy_images（P4 T14）─────────────────────────────────────────────────────

def test_copy_images_clones_files_with_new_ids(isolated_root: Path):
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # valid jpeg magic
    id1 = images.save_image("draftA", jpeg)
    new_ids = images.copy_images("draftA", "draftB", [id1])
    assert len(new_ids) == 1
    assert new_ids[0] != id1
    p = images.get_image_path(new_ids[0])
    assert p is not None
    assert p.read_bytes() == jpeg


def test_copy_images_skips_missing(isolated_root: Path):
    assert images.copy_images("draftA", "draftB", ["nope"]) == []
