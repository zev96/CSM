"""Article-side helpers: title candidates, single-block polish, export."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import export_service, polish_service, title_service
from ..services.llm_factory import LLMConfigError

router = APIRouter(tags=["article"], dependencies=[RequireToken])


# ── /api/title ──────────────────────────────────────────────────────────────
class TitleBody(BaseModel):
    keyword: str = Field(min_length=1)
    template_type: str | None = None
    n_candidates: int = Field(default=3, ge=1, le=10)
    provider: str | None = None
    model: str | None = None


@router.post("/api/title")
async def generate_title(body: TitleBody) -> dict[str, Any]:
    try:
        candidates = title_service.generate(**body.model_dump())
    except LLMConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"candidates": candidates}


# ── /api/polish/block ───────────────────────────────────────────────────────
class PolishBody(BaseModel):
    text: str = Field(min_length=1)
    skill_id: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=0.6, ge=0.0, le=2.0)


@router.post("/api/polish/block")
async def polish_block(body: PolishBody) -> dict[str, str]:
    try:
        out = polish_service.polish_block(**body.model_dump())
    except LLMConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"text": out}


# ── /api/export/{format} ────────────────────────────────────────────────────
class ExportBody(BaseModel):
    keyword: str = Field(min_length=1)
    final_text: str = Field(min_length=1)
    out_dir: str | None = None
    include_dedup_report: bool = False
    template_name: str | None = None


@router.post("/api/export/{fmt}")
async def export_article_route(fmt: str, body: ExportBody) -> dict[str, Any]:
    if fmt not in ("markdown", "docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format: {fmt} (use 'markdown' or 'docx')",
        )
    try:
        return export_service.export(fmt=fmt, **body.model_dump())  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
