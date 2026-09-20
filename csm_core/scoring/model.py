"""评分结果模型。"""
from __future__ import annotations

from pydantic import BaseModel


class ScorePart(BaseModel):
    key: str
    label: str
    points: float            # 扣分（正数）；total = 100 - Σpoints
    detail: str

