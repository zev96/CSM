"""Angle — per-request 选材意图（人群/卖点/语调），全可空。"""
from __future__ import annotations
from pydantic import BaseModel, Field


class Angle(BaseModel):
    audience: str | None = None        # 16 人群之一，如 "铲屎官"
    sellpoints: list[str] = Field(default_factory=list)  # 卖点维度键，0..N
    tone: str | None = None            # "口语" | "专业" | "极客"

    def is_empty(self) -> bool:
        """等价于「不传 angle」⇔ 今天行为。"""
        return not self.audience and not self.sellpoints and not self.tone
