"""Thin service for the vault writer routes.

Resolves cfg.vault_root, refreshes the index via vault_service.get (增量刷新；
refresh 每次 stat 巡走全树，picker 仍看到当前磁盘状态), validates folder/filename
stay inside the root, and delegates to the pure csm_core.vault.writer engine.
Invalidates the vault cache after writes so the new note shows up in
subsequent scans.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from csm_core.vault import folder_profile, writer
from . import config_service, vault_service


def _root() -> Path:
    cfg = config_service.load()
    if not cfg.vault_root:
        raise ValueError("vault_root 未配置 — 请先在「设置」里指定素材库路径")
    root = Path(cfg.vault_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"素材库路径不存在: {root}")
    return root


def _validate(root: Path, rel_folder: str, filename: str) -> None:
    if (not filename or " " in filename or "/" in filename
            or "\\" in filename or not filename.endswith(".md")):
        raise ValueError("文件名非法：不能含空格/路径分隔符，须以 .md 结尾")
    folder = (root / rel_folder).resolve()
    rres = root.resolve()
    if folder != rres and rres not in folder.parents:
        raise ValueError("目标文件夹越界")
    if not folder.is_dir():
        raise ValueError("目标文件夹不存在")


def list_folders() -> list[dict[str, Any]]:
    idx = vault_service.get(_root())   # 增量刷新即可：写盘后 invalidate 已保证下次全量
    return [asdict(p) for p in folder_profile.list_writable_folders(idx)]


def plan(*, rel_folder, filename, frontmatter, body_shape, variants, spec_rows, today) -> dict:
    root = _root()
    _validate(root, rel_folder, filename)
    p = writer.plan_note(
        root, rel_folder=rel_folder, filename=filename, frontmatter=frontmatter,
        body_shape=body_shape, today=today, variants=variants, spec_rows=spec_rows)
    return asdict(p)


def commit(*, rel_folder, filename, frontmatter, body_shape, variants, spec_rows, today) -> dict:
    root = _root()
    _validate(root, rel_folder, filename)
    p = writer.plan_note(
        root, rel_folder=rel_folder, filename=filename, frontmatter=frontmatter,
        body_shape=body_shape, today=today, variants=variants, spec_rows=spec_rows)
    if p.conflict:
        raise FileExistsError(p.rel_path)
    receipt = writer.commit_note(p, root)
    vault_service.invalidate()
    return asdict(receipt)


def undo(receipt: dict) -> dict:
    root = _root()
    warnings = writer.undo_write(writer.WriteReceipt(**receipt), root)
    vault_service.invalidate()
    return {"undone": True, "warnings": warnings}
