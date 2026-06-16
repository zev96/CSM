"""小红书图文笔记编辑器路由 —— 草稿 CRUD（P0）。

图片上传/serve（P2）、AI 生成/润色（P3）、ai_prompts（P4）后续追加到本文件。
持久化走独立 ``csm_core.xhs.storage``（自有 xhs.db），与 mining/monitor 解耦。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from csm_core.xhs import storage as xhs_storage

from ..auth import RequireToken
from ..services import xhs_ai_service, xhs_images_service
from ..services.llm_factory import LLMConfigError

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
    # 约定：字段为 None = 「该字段不更新」（保持原值）。P0 不支持把 theme_id
    # 清回 NULL（主题切换在 P3 才需要）——与 storage.update_draft 的语义一致。
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
    created = xhs_storage.get_draft(draft_id)
    if created is None:
        # 刚插入就读不回来 = 写入异常；别给前端发「201 + 空 body」害它读 d.id 崩溃
        raise HTTPException(status_code=500, detail="draft creation failed")
    return created


@router.get("/api/xhs/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    d = xhs_storage.get_draft(draft_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    return d


@router.patch("/api/xhs/drafts/{draft_id}")
def patch_draft(draft_id: str, body: DraftPatch) -> dict[str, Any]:
    # 若本次 PATCH 改 image_ids，先取旧的，便于事后删掉被移除的图片文件（§8）。
    old = xhs_storage.get_draft(draft_id) if body.image_ids is not None else None
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
    if body.image_ids is not None and old is not None:
        removed = sorted(set(old["image_ids"]) - set(body.image_ids))
        if removed:
            xhs_images_service.delete_images(removed)
    return updated


@router.delete("/api/xhs/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str) -> None:
    if not xhs_storage.delete_draft(draft_id):
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    # 级联删 xhs_images/{draft_id}/ 整目录（§8 孤儿清理）。
    xhs_images_service.delete_draft_images(draft_id)


# ── 图片（P2）────────────────────────────────────────────────────────────────
_EXT_TO_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.post("/api/xhs/drafts/{draft_id}/images", status_code=201)
async def upload_image(draft_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Multipart 上传。bytes 走 magic-byte 嗅探 —— 不信 Content-Type/文件名。

    上传只落盘 + 返回 image_id；把 image_id 挂进草稿的 image_ids 由前端随后
    PATCH 完成（与 mining 一致）。
    """
    if xhs_storage.get_draft(draft_id) is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    content = await file.read()
    try:
        image_id = xhs_images_service.save_image(draft_id, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "image_id": image_id,
        "url": f"/api/xhs/images/{image_id}",
        "size": len(content),
    }


@router.get("/api/xhs/images/{image_id}")
def get_image(image_id: str) -> FileResponse:
    path = xhs_images_service.get_image_path(image_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
    media_type = _EXT_TO_MEDIA_TYPE.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=media_type)


# ── AI 助手（P3）─────────────────────────────────────────────────────────────
class AiGenerateBody(BaseModel):
    intent: str = ""


class AiPolishBody(BaseModel):
    text: str = ""


def _llm_http_error(e: Exception) -> HTTPException:
    """LLMConfigError → 503 llm_not_configured；其余 LLM 异常 → 502 llm_error。

    与 mining AI 路由同款映射，前端据 detail.code 区分「去设置」与普通报错。
    """
    if isinstance(e, LLMConfigError):
        return HTTPException(
            status_code=503,
            detail={"code": "llm_not_configured", "detail": str(e)},
        )
    return HTTPException(
        status_code=502,
        detail={"code": "llm_error", "detail": str(e) or e.__class__.__name__},
    )


@router.post("/api/xhs/ai/generate")
def ai_generate(body: AiGenerateBody) -> dict[str, Any]:
    """输入主题/关键词 → 返回 {title, body, topics}（前端决定是否覆盖填入）。"""
    if not body.intent.strip():
        raise HTTPException(status_code=400, detail="intent required")
    try:
        return xhs_ai_service.generate_note(body.intent)
    except LLMConfigError as e:
        raise _llm_http_error(e)
    except Exception as e:  # noqa: BLE001 —— LLM client 可能抛任何异常
        logger.exception("xhs ai_generate failed")
        raise _llm_http_error(e)


@router.post("/api/xhs/ai/polish")
def ai_polish(body: AiPolishBody) -> dict[str, Any]:
    """输入正文 → 返回 {body: 润色后正文}。"""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    try:
        return {"body": xhs_ai_service.polish_note(body.text)}
    except LLMConfigError as e:
        raise _llm_http_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("xhs ai_polish failed")
        raise _llm_http_error(e)
