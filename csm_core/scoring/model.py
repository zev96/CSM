"""评分结果模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScorePart(BaseModel):
    key: str
    label: str
    points: float            # 扣分（正数）；total = 100 - Σpoints
    detail: str


class ScoreReport(BaseModel):
    total: float             # 0-100
    parts: list[ScorePart] = Field(default_factory=list)
