"""Local image storage for 小红书 draft attachments (P2).

1:1 仿 ``mining_images_service``，差异：
* 根目录 ``xhs_images``（非 mining_images）
* 子目录键是 draft_id(str)（非 video_id(int)）—— 每草稿一个子目录
* 多一个 ``delete_draft_images(draft_id)`` —— 删草稿时整目录清掉（§8 级联）

安全约束（与 mining 同）：
* magic-bytes 嗅探前 12 字节，只认 jpeg/png/webp（不信 Content-Type，
  防 .html 当 image/png 上传后经静态路由 XSS）
* 5MB 硬上限（写盘前）
* uuid4 image_id 不可枚举
* get_image_path / delete_draft_images 解析后校验仍在 image_root() 内，
  防 ``../`` 穿越
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from csm_core import config as core_config

logger = logging.getLogger(__name__)


_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF = b"RIFF"
_WEBP_FORMAT = b"WEBP"


def image_root() -> Path:
    """Per-user dir where every xhs image lives. Auto-creates; idempotent."""
    root = core_config.default_config_dir() / "xhs_images"
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
    if len(content) >= 12 and content[:4] == _WEBP_RIFF and content[8:12] == _WEBP_FORMAT:
        return "webp"
    return None


def save_image(draft_id: str, content: bytes) -> str:
    """Validate, write to disk under ``xhs_images/{draft_id}/``, return image_id.

    Raises:
        ValueError("invalid draft_id") on traversal-shaped draft_id.
        ValueError("image too large") when content exceeds 5 MB.
        ValueError("unsupported image type") on magic-bytes mismatch.
    """
    if not draft_id or "/" in draft_id or "\\" in draft_id or ".." in draft_id:
        raise ValueError("invalid draft_id")
    if len(content) > _MAX_BYTES:
        raise ValueError("image too large")
    ext = _detect_ext(content)
    if ext is None:
        raise ValueError("unsupported image type")
    image_id = uuid.uuid4().hex
    draft_dir = image_root() / draft_id
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / f"{image_id}.{ext}"
    path.write_bytes(content)
    return image_id


def get_image_path(image_id: str) -> Path | None:
    """Resolve image_id back to a path on disk, or None if missing.

    Scans every per-draft subdir under image_root(). Treats traversal-shaped
    IDs as not-found and re-checks the resolved path stays under the root.
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
                if not resolved.is_relative_to(root_resolved):
                    return None
                return resolved
    return None


def delete_images(image_ids: list[str]) -> None:
    """Best-effort cleanup; missing files are logged but never raise.

    不做跨草稿引用计数 —— 每草稿图片独立（每次上传生成新 uuid image_id，
    草稿间不共享），所以这里直接删是安全的。
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


def copy_images(src_draft_id: str, dst_draft_id: str, image_ids: list[str]) -> list[str]:
    """把 src 草稿的若干图片复制进 dst 草稿目录，返回新 image_id 列表（缺失的跳过）。

    复用 save_image：在 dst 子目录落新文件、生成新 id，不共享文件路径，
    避免删 src 草稿时误删 dst 草稿的图片。
    src_draft_id 是 API 契约参数；get_image_path 按 image_id 全局查找，
    实际不需要用到 src_draft_id。
    """
    new_ids: list[str] = []
    for image_id in image_ids:
        path = get_image_path(image_id)
        if path is None:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        new_ids.append(save_image(dst_draft_id, data))
    return new_ids


def delete_draft_images(draft_id: str) -> None:
    """删草稿级联：整个 ``xhs_images/{draft_id}/`` 目录 rmtree（§8）。

    带 ``..`` / 分隔符防护 + resolve 后再校验仍在 root 内 —— draft_id 来自
    URL path，虽然实际只会是 DB 里的 uuid hex，仍按防御式处理，绝不 rmtree
    到 root 之外。目录不存在时静默 no-op。
    """
    if not draft_id or "/" in draft_id or "\\" in draft_id or ".." in draft_id:
        return
    root = image_root()
    target = root / draft_id
    try:
        resolved = target.resolve()
    except OSError:
        return
    if not resolved.is_relative_to(root.resolve()):
        return
    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)
