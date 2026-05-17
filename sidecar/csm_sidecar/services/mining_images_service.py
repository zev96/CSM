"""Local image storage for comment-draft attachments (Outreach Phase 2).

Why a local-filesystem store instead of sqlite blobs or OSS:
* sqlite would bloat the WAL and slow down every list query
* OSS is overkill — these images never leave the user's machine; the
  outreach contractor receives them via CSV + zip export
* a flat dir keyed on image_id lets the static route hand off the file
  to FastAPI's ``FileResponse`` with zero copying

Safety constraints (spec §6.2):
* magic-bytes sniff the first 12 bytes; reject anything that isn't
  jpeg/png/webp (don't trust Content-Type — defends against `.html`
  uploaded as image/png to mount an XSS via the static route)
* hard 5 MB cap pre-write to keep a buggy frontend from filling the
  user's disk
* uuid4 image_id is unguessable, so a leaked URL doesn't enumerate
* ``get_image_path`` resolves and verifies the result lives under
  ``image_root()`` before returning — guards against ``../``-style
  traversal even though image_id is opaque

This module is filesystem-only. Storage of which image belongs to
which comment lives in ``video_comments.image_ids_json`` (T1).
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from csm_core import config as core_config

logger = logging.getLogger(__name__)


_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

# Magic-byte signatures. WEBP is the long one: bytes 0-3 are "RIFF",
# bytes 8-11 are "WEBP". Other two are simple prefix checks.
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF = b"RIFF"
_WEBP_FORMAT = b"WEBP"


def image_root() -> Path:
    """Per-user dir where every mining image lives.

    The codebase convention (see ``csm_core.config.default_config_dir``)
    is %LOCALAPPDATA%/CSM-Data on Windows; the plan's reference to
    ``appdirs.user_data_dir`` aligns with that intent — we use the
    existing helper so both PyQt and sidecar see the same path.

    Auto-creates the dir; safe to call repeatedly.
    """
    root = core_config.default_config_dir() / "mining_images"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _detect_ext(content: bytes) -> str | None:
    """Sniff first ~12 bytes for jpeg/png/webp. None = unrecognized."""
    if len(content) < 4:
        return None
    if content.startswith(_JPEG_MAGIC):
        return "jpg"
    if content.startswith(_PNG_MAGIC):
        return "png"
    # WEBP: "RIFF" .... "WEBP" at offset 8
    if len(content) >= 12 and content[:4] == _WEBP_RIFF and content[8:12] == _WEBP_FORMAT:
        return "webp"
    return None


def save_image(video_id: int, content: bytes) -> str:
    """Validate, write to disk, return the new image_id.

    Raises:
        ValueError("image too large") when content exceeds 5 MB.
        ValueError("unsupported image type") on magic-bytes mismatch.
    """
    if len(content) > _MAX_BYTES:
        raise ValueError("image too large")
    ext = _detect_ext(content)
    if ext is None:
        raise ValueError("unsupported image type")
    image_id = uuid.uuid4().hex
    video_dir = image_root() / str(video_id)
    video_dir.mkdir(parents=True, exist_ok=True)
    path = video_dir / f"{image_id}.{ext}"
    path.write_bytes(content)
    return image_id


def get_image_path(image_id: str) -> Path | None:
    """Resolve image_id back to a path on disk, or None if missing.

    Scans every per-video subdirectory under image_root() — fine for the
    expected scale (a few thousand images at most). If lookup ever
    becomes a hotspot we can add an index file.

    Treats traversal-shaped IDs (``../foo``) as not-found by re-checking
    that the resolved path still lives under image_root().resolve().
    """
    if not image_id or "/" in image_id or "\\" in image_id or ".." in image_id:
        return None
    root = image_root()
    root_resolved = root.resolve()
    try:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return None
    for sub in subdirs:
        for ext in ("jpg", "png", "webp"):
            candidate = sub / f"{image_id}.{ext}"
            if candidate.exists():
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                # Path.is_relative_to is 3.9+; CSM runs 3.10+ per pyproject.
                if not resolved.is_relative_to(root_resolved):
                    return None
                return resolved
    return None


def delete_images(image_ids: list[str]) -> None:
    """Best-effort cleanup; missing files are logged but never raise.

    Called when a comment is PATCHed/DELETEd and one or more image_ids
    are no longer referenced. We don't reference-count across other
    comments — comments cannot share an image_id by design (composer
    uploads a fresh image_id per file), so deletion here is safe.
    """
    for image_id in image_ids:
        path = get_image_path(image_id)
        if path is None:
            logger.debug("delete_images: image %s already gone", image_id)
            continue
        try:
            path.unlink()
        except OSError as e:
            logger.warning("delete_images: unlink %s failed: %s", path, e)
