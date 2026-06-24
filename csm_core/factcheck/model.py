"""Fact-check result models."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class Violation(BaseModel):
    kind: Literal["number", "cert"]
    value: str            # 成稿里的原文 token，如 "250AW" / "CCC"
    number: float | None = None  # number 违规的归一值（万已展开），cert=None；前端放行回传它
    sentence: str         # 所在句子（审查面板定位用）
    suggestion: str       # 放行建议提示


class FactCheckReport(BaseModel):
    ok: bool
    violations: list[Violation] = Field(default_factory=list)
