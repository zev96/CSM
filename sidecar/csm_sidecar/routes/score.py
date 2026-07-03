"""POST /api/score —— 无状态成稿评分。text→ScoreReport（scoring 关→total null）。"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import score_service

router = APIRouter(tags=["score"], dependencies=[RequireToken])


class ScoreBody(BaseModel):
    text: str
    factcheck_violations: int = Field(default=0, ge=0)
    completeness_missing: int = Field(default=0, ge=0)


@router.post("/api/score")
def score(body: ScoreBody) -> dict[str, Any]:
    return score_service.score_text(
        body.text, factcheck_violations=body.factcheck_violations,
        completeness_missing=body.completeness_missing)
