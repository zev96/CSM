"""Article-side helpers: title candidates, single-block polish, export."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import export_service, feedback_service, polish_service, title_service
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
def generate_title(body: TitleBody) -> dict[str, Any]:
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
def polish_block(body: PolishBody) -> dict[str, str]:
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
    # 反馈采集（§6）—— 关联 job + 质检卡已算的分数/未决禁区；后端不回传、纯落库。
    job_id: str | None = None
    score: float | None = None
    score_json: str | None = None
    lint_unresolved: int = 0


@router.post("/api/export/{fmt}")
def export_article_route(fmt: str, body: ExportBody) -> dict[str, Any]:
    if fmt not in ("markdown", "docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format: {fmt} (use 'markdown' or 'docx')",
        )
    try:
        # 显式传 export_service 认识的字段 —— 别 **model_dump() 把反馈字段泄给它。
        result = export_service.export(
            fmt=fmt, keyword=body.keyword, final_text=body.final_text,
            out_dir=body.out_dir, include_dedup_report=body.include_dedup_report,
            template_name=body.template_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    # 导出成功后采集（record_export 自身 fail-open，路由无需再包 try）。
    # document_path 优先存 history 镜像路径 —— list_recent 扫的是镜像，据此 join（§7.3）。
    feedback_service.record_export(
        body.job_id,
        document_path=result.get("history_path") or result.get("document", ""),
        fmt=result.get("format", fmt), final_text=body.final_text,
        score=body.score, score_json=body.score_json,
        lint_unresolved=body.lint_unresolved, factcheck_blocked=0,
    )
    return result
