"""BrandModelMemory — resolver output (in-memory, never persisted)."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class SpecValue(BaseModel):
    field: str                       # 参数名，如 "吸力(AW)"
    raw: str                         # 原始单元格文本，如 "15/25/40min"
    numbers: list[float] = Field(default_factory=list)  # 解析出的数值（空=占位/非数值）
    unit: str = ""                   # 单位，如 "min" / "Pa"
    is_approx: bool = False          # 含 约/近/≤/起 等近似标记
    is_placeholder: bool = False     # 占位/缺口（0/未说明/无/-/暂无…），供缺口体检
    section: str = ""                # 所属 H2 小节名(原文),如 "核心净化性能"


class BrandModelMemory(BaseModel):
    brand: str
    model: str
    category: str                    # 品类，如 "吸尘器"
    role: str                        # "主推" | "竞品"
    specs: dict[str, SpecValue] = Field(default_factory=dict)
    certs: list[str] = Field(default_factory=list)
    scripts: dict[str, list[str]] = Field(default_factory=dict)  # 维度 -> 变体
    endorsements: list[str] = Field(default_factory=list)        # 品牌级
    intro: list[str] = Field(default_factory=list)
    tests: dict[str, str] = Field(default_factory=dict)          # 测试项 -> 结果
    coverage: dict[str, Any] = Field(default_factory=dict)       # 缺口体检
