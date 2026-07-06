"""Vault scanning + note query routes."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from csm_core.vault.brand_registry import build_brand_registry

from ..auth import RequireToken
from ..services import config_service, fact_service, vault_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vault"], dependencies=[RequireToken])


class VaultScanRequest(BaseModel):
    # Optional — if absent we use AppConfig.vault_root. Letting callers
    # override is useful for "preview a different folder before saving"
    # flows in settings.
    root: str | None = Field(default=None, description="Vault root directory")


class VaultScanResponse(BaseModel):
    root: str
    note_count: int
    warnings: list[str]


@router.post("/api/vault/scan", response_model=VaultScanResponse)
def scan_vault(body: VaultScanRequest) -> VaultScanResponse:
    root_str = body.root or config_service.load().vault_root
    if not root_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no vault_root configured; pass body.root or set AppConfig.vault_root",
        )
    root = Path(root_str)
    if not root.exists() or not root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"vault root not found: {root}",
        )
    index = vault_service.scan(root)
    # 事实传导（§7.2）：重建索引后检测型号参数变更，入 pending 队列供前端拉
    # /api/facts/changes → 通知。fail-safe：检测失败不影响扫描结果。
    try:
        fact_service.detect_changes(index, build_brand_registry(root))
    except Exception:
        logger.debug("vault scan fact detect failed", exc_info=True)
    return VaultScanResponse(**vault_service.index_summary(index))


@router.get("/api/vault/dirs")
def list_dirs() -> dict[str, Any]:
    """List leaf directories under vault_root that directly contain .md files.

    Mirrors ``csm_gui.widgets.slot_tree_widget._scan_vault_dirs`` —
    返回的是「叶子目录」（其它已收录目录的父目录会被剥掉），用于级联文件夹
    选择器。前端拿到后按 ``/`` 拆分组成树。
    """
    cfg = config_service.load()
    root_str = cfg.vault_root
    if not root_str:
        return {"root": "", "dirs": []}
    root = Path(root_str)
    if not root.exists() or not root.is_dir():
        return {"root": str(root), "dirs": []}

    skip_dirs = {".git", ".obsidian", "node_modules", "__pycache__", ".venv"}
    candidates: list[str] = []
    try:
        for p in sorted(root.rglob("*")):
            if not p.is_dir():
                continue
            try:
                rel_parts = p.relative_to(root).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part in skip_dirs for part in rel_parts):
                continue
            try:
                if not any(c.suffix == ".md" for c in p.iterdir() if c.is_file()):
                    continue
            except OSError:
                continue
            candidates.append("/".join(rel_parts))
            if len(candidates) >= 500:
                break
    except OSError:
        pass

    cset = set(candidates)
    leaves = sorted(
        d for d in candidates
        if not any(other.startswith(d + "/") for other in cset)
    )
    return {"root": str(root), "dirs": leaves}


@router.get("/api/vault/notes")
def list_notes(
    module: str | None = Query(default=None, description="Module path filter, e.g. '营销资料库/标题模块'"),
) -> dict[str, Any]:
    """List notes from the most recent scan. Returns 409 if no scan yet."""
    index = vault_service.cached()
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no vault index yet; call POST /api/vault/scan first",
        )
    notes = index.query(module=module) if module else index.notes
    return {
        "root": str(index.root),
        "module": module,
        "count": len(notes),
        "notes": [vault_service.note_to_dict(n) for n in notes],
    }


@router.get("/api/vault/attributes")
def list_attributes(
    module: str | None = Query(
        default=None,
        description="Scope to notes whose path is under this module, e.g. '营销资料库/产品模块/吸尘器'",
    ),
) -> dict[str, Any]:
    """Aggregate distinct frontmatter keys across the (optionally scoped) note set.

    Drives the BlockEditor 筛选 dropdown: instead of having the user type
    attribute names like "素材类型" from memory, the UI shows a select
    populated from the actual keys present in the Vault.

    For each key we also collect a *sample* of its distinct values (capped
    at 20 per key — beyond that the dropdown would be a wall of text, and
    free-text input is more useful for high-cardinality keys like titles).

    Returns 409 if no scan has been run yet (same convention as /notes).
    """
    index = vault_service.cached()
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no vault index yet; call POST /api/vault/scan first",
        )
    notes = index.query(module=module) if module else index.notes

    # key -> ordered set of stringified values (preserve insertion order to
    # be visually stable; users see "the values as they appear in disk").
    seen: dict[str, dict[str, None]] = {}
    counts: dict[str, int] = {}
    for n in notes:
        fm = n.frontmatter or {}
        for k, v in fm.items():
            if v is None or v == "":
                continue
            counts[k] = counts.get(k, 0) + 1
            bucket = seen.setdefault(k, {})
            # Lists in frontmatter (e.g. `tags: [a, b]`) — explode each entry.
            if isinstance(v, list):
                for item in v:
                    if item is None or item == "":
                        continue
                    bucket.setdefault(str(item), None)
            else:
                bucket.setdefault(str(v), None)

    attributes = [
        {
            "key": k,
            "note_count": counts[k],
            "value_count": len(seen[k]),
            # Cap to 20 per key —— a long dropdown of every distinct title
            # would be useless; UI falls back to free-text when truncated.
            "sample_values": list(seen[k].keys())[:20],
        }
        for k in sorted(seen.keys(), key=lambda x: (-counts[x], x))
    ]
    return {
        "root": str(index.root),
        "module": module,
        "count": len(notes),
        "attributes": attributes,
    }
