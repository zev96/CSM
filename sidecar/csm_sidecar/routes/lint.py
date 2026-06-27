"""POST /api/lint —— 无状态禁区扫描。text→{hits, fixed_text}。"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import RequireToken
from ..services import lint_service

router = APIRouter(tags=["lint"], dependencies=[RequireToken])


class LintBody(BaseModel):
    text: str


@router.post("/api/lint")
def lint(body: LintBody) -> dict[str, Any]:
    return lint_service.scan_text(body.text)
