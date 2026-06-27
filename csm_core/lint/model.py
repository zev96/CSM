"""禁区 lint 结果模型。"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["meta_speak", "absolute", "traffic", "emoji", "dash", "quote"]


class LintHit(BaseModel):
    category: Category
    text: str          # 命中原文片段
    start: int         # 字符偏移
    end: int           # start + len(text)
    sentence: str      # 所在句子（≤80）
    fixable: bool      # True=机械三类，可一键清
    suggestion: str


class LintReport(BaseModel):
    hits: list[LintHit] = Field(default_factory=list)
    fixed_text: str
