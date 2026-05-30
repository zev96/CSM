"""GEO 卡位监控数据模型。

分层：
- Citation / GeoAnswer  —— provider 采集层输出（原始信源 + 完整回答）
- RecommendedEntity / ClassifiedCitation / GeoExtraction —— 抽取层输出
- GeoCell —— 一个 (关键词,平台) cell 的最终聚合单元，写入 geo_cells/geo_citations
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

Sentiment = Literal["pos", "neu", "neg", "na"]
AnswerStatus = Literal["ok", "empty", "blocked", "error"]


class Citation(BaseModel):
    url: str
    title: str = ""


class GeoAnswer(BaseModel):
    platform: str
    keyword: str
    answer_text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    status: AnswerStatus = "ok"
    error: str = ""


class RecommendedEntity(BaseModel):
    name: str
    position: int           # 1-based
    is_target: bool = False


class ClassifiedCitation(BaseModel):
    url: str
    title: str = ""
    domain: str = ""
    source_type: str = "其他"


class GeoExtraction(BaseModel):
    mentioned: bool = False
    target_rank: int = -1   # -1 = 未提及/未进推荐列表
    sentiment: Sentiment = "na"
    recommended: list[RecommendedEntity] = Field(default_factory=list)
    citations: list[ClassifiedCitation] = Field(default_factory=list)
    summary: str = ""


class GeoCell(BaseModel):
    platform: str
    keyword: str
    mentioned: bool = False
    rank: int = -1
    sentiment: Sentiment = "na"
    answer_text: str = ""
    status: AnswerStatus = "ok"   # ok/empty/blocked/error，与 GeoAnswer 同值域
    raw: dict[str, Any] = Field(default_factory=dict)
    citations: list[ClassifiedCitation] = Field(default_factory=list)
