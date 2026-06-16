"""小红书图文笔记编辑器路由 —— 草稿 CRUD（P0）。

图片上传/serve（P2）、AI 生成/润色（P3）、ai_prompts（P4）后续追加到本文件。
持久化走独立 ``csm_core.xhs.storage``（自有 xhs.db），与 mining/monitor 解耦。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from csm_core.xhs import storage as xhs_storage

from ..auth import RequireToken

logger = logging.getLogger(__name__)

router = APIRouter(tags=["xhs"], dependencies=[RequireToken])


class DraftCreate(BaseModel):
    title: str = ""
    body: str = ""
    topics: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)
    cover_index: int = 0
    theme_id: str | None = None


class DraftPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    topics: list[str] | None = None
    image_ids: list[str] | None = None
    cover_index: int | None = None
    theme_id: str | None = None


@router.get("/api/xhs/drafts")
def list_drafts() -> dict[str, Any]:
    return {"drafts": xhs_storage.list_drafts()}


@router.post("/api/xhs/drafts", status_code=201)
def create_draft(body: DraftCreate) -> dict[str, Any]:
    draft_id = xhs_storage.create_draft(
        title=body.title,
        body=body.body,
        topics=body.topics,
        image_ids=body.image_ids,
        cover_index=body.cover_index,
        theme_id=body.theme_id,
    )
    return xhs_storage.get_draft(draft_id) or {}


@router.get("/api/xhs/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    d = xhs_storage.get_draft(draft_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    return d


@router.patch("/api/xhs/drafts/{draft_id}")
def patch_draft(draft_id: str, body: DraftPatch) -> dict[str, Any]:
    updated = xhs_storage.update_draft(
        draft_id,
        title=body.title,
        body=body.body,
        topics=body.topics,
        image_ids=body.image_ids,
        cover_index=body.cover_index,
        theme_id=body.theme_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    return updated


@router.delete("/api/xhs/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str) -> None:
    if not xhs_storage.delete_draft(draft_id):
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
