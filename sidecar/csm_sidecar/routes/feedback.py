"""反馈学习 + 事实传导只读端点（§6.4 / §7.2-7.3）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from csm_core.vault.brand_registry import build_brand_registry

from ..auth import RequireToken
from ..services import config_service, fact_service, feedback_service, vault_service

router = APIRouter(tags=["feedback"], dependencies=[RequireToken])


@router.get("/api/feedback/stats")
def feedback_stats() -> dict:
    """素材/角度使用反馈统计（两张表）。空库返回空表。"""
    return feedback_service.get_feedback_stats()


@router.get("/api/facts/changes")
def facts_changes() -> dict:
    """取走并清空 pending 型号变更（App 启动/重建索引后拉一次 → 通知）。"""
    return {"changes": fact_service.drain_changes()}


@router.get("/api/facts/diff")
def facts_diff(model: str = Query(..., min_length=1)) -> dict:
    """某型号「最近成稿快照 vs 当前 vault」字段 diff（历史页 hover 按需取）。"""
    cfg = config_service.load()
    if not cfg.vault_root:
        raise HTTPException(status_code=400, detail="vault_root 未配置")
    root = Path(cfg.vault_root)
    index = vault_service.get(root)
    registry = build_brand_registry(root)
    return {"model": model, "changed": fact_service.diff_for_model(model, index, registry)}
