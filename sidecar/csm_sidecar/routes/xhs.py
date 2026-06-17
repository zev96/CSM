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
from ..services import config_service, xhs_ai_service, xhs_images_service
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


@router.post("/api/xhs/drafts/{draft_id}/duplicate", status_code=201)
def duplicate_draft(draft_id: str) -> dict[str, Any]:
    """复制草稿（副本）：复制文本字段 + 独立拷贝图片文件，返回新草稿完整 dict。

    图片走 copy_images 生成全新 image_id，不共享文件路径——避免删源草稿时
    误删副本图片（各草稿图片目录独立，§8 级联安全）。
    """
    src = xhs_storage.get_draft(draft_id)
    if src is None:
        raise HTTPException(status_code=404, detail="not found")
    new_id = xhs_storage.create_draft(
        title=(src["title"] or "") + "（副本）",
        body=src["body"],
        topics=src["topics"],
        cover_index=src["cover_index"],
        theme_id=src["theme_id"],
    )
    new_image_ids = xhs_images_service.copy_images(draft_id, new_id, src["image_ids"])
    effective_cover = min(src["cover_index"], len(new_image_ids) - 1) if new_image_ids else 0
    xhs_storage.update_draft(new_id, image_ids=new_image_ids, cover_index=effective_cover)
    result = xhs_storage.get_draft(new_id)
    if result is None:
        raise HTTPException(status_code=500, detail="duplicate failed")
    return result


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


# ── 自定义素材（P4）──────────────────────────────────────────────────────────
_ASSET_KINDS = {"template", "copy", "topic_group"}


class CustomAssetCreate(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/xhs/custom-assets")
def list_custom_assets(kind: str | None = None) -> dict[str, Any]:
    if kind is not None and kind not in _ASSET_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")
    return {"assets": xhs_storage.list_custom_assets(kind=kind)}


@router.post("/api/xhs/custom-assets", status_code=201)
def create_custom_asset(body: CustomAssetCreate) -> dict[str, Any]:
    if body.kind not in _ASSET_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")
    if not body.payload:
        raise HTTPException(status_code=400, detail="empty payload")
    asset = xhs_storage.create_custom_asset(kind=body.kind, payload=body.payload)
    return {"asset": asset}


@router.delete("/api/xhs/custom-assets/{asset_id}", status_code=204)
def delete_custom_asset(asset_id: str) -> None:
    if not xhs_storage.delete_custom_asset(asset_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


# ── AI Prompts 配置（P4 T8）──────────────────────────────────────────────────


class XhsAiPromptsPatch(BaseModel):
    """PATCH /api/xhs/ai_prompts 体。空字符串 = 回内置默认。"""

    generate: str | None = None
    polish: str | None = None


def _xhs_ai_prompts_payload() -> dict[str, Any]:
    cfg = config_service.load()
    return {
        "generate": {
            "current": cfg.xhs_generate_prompt,
            "default": xhs_ai_service.DEFAULT_GENERATE_SYSTEM,
        },
        "polish": {
            "current": cfg.xhs_polish_prompt,
            "default": xhs_ai_service.DEFAULT_POLISH_SYSTEM,
        },
    }


@router.get("/api/xhs/ai_prompts")
def get_xhs_ai_prompts() -> dict[str, Any]:
    """返回小红书 AI 生成/润色的当前 + 内置默认 prompt。"""
    return _xhs_ai_prompts_payload()


@router.patch("/api/xhs/ai_prompts")
def patch_xhs_ai_prompts(body: XhsAiPromptsPatch) -> dict[str, Any]:
    """更新 prompt。字段为 None=不动；空字符串=清空回内置默认。无字段→400。"""
    updates: dict[str, Any] = {}
    if body.generate is not None:
        updates["xhs_generate_prompt"] = body.generate
    if body.polish is not None:
        updates["xhs_polish_prompt"] = body.polish
    if not updates:
        raise HTTPException(status_code=400, detail="no fields provided")
    config_service.patch(updates)
    return _xhs_ai_prompts_payload()
