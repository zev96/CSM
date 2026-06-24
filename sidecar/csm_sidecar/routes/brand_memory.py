"""Read-only brand/model memory routes (Phase 1 Plan 5a)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..auth import RequireToken
from ..services import brand_memory_service, config_service

router = APIRouter(tags=["brand_memory"], dependencies=[RequireToken])


def _cfg_or_400():
    cfg = config_service.load()
    if not cfg.vault_root:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vault_root 未配置 — 请先在「设置」里指定素材库路径",
        )
    return cfg


@router.get("/api/brand-memory")
def list_brand_memory() -> dict[str, Any]:
    cfg = _cfg_or_400()
    models = brand_memory_service.list_models(
        Path(cfg.vault_root),
        category=cfg.user_product or "吸尘器",
        own_brands=set(cfg.brand_memory.own_brands),
    )
    return {"count": len(models), "models": models}


@router.get("/api/brand-memory/{model}")
def get_brand_memory(model: str) -> dict[str, Any]:
    cfg = _cfg_or_400()
    detail = brand_memory_service.get_model_detail(
        Path(cfg.vault_root), model,
        category=cfg.user_product or "吸尘器",
        own_brands=set(cfg.brand_memory.own_brands),
        variant_cap=cfg.brand_memory.inject_variant_cap,
        endorsement_cap=cfg.brand_memory.inject_endorsement_cap,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"型号未找到: {model}")
    return detail
