"""Build the per-generation fact whitelist used by the export-time factcheck.

白名单 = 本次注入源里出现的数字 ∪ 该型号 specs 数值 ∪ 认证。判据：成稿
里出现的数字若不在白名单 = LLM 凭空引入。这里只构建白名单；匹配/拦截在
Plan 3 的 csm_core/factcheck/。

Plan 3 直接用 ``val in wl.numbers`` 判membership 即可：本域数值都是良态
float（220.0、120000.0 这类），int/float 与 1.2/1.20 在 Python 里相等，
无需 math.isclose。
"""
from __future__ import annotations
import re
from pydantic import BaseModel, Field
from .model import BrandModelMemory

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*万")


class FactWhitelist(BaseModel):
    numbers: set[float] = Field(default_factory=set)
    certs: set[str] = Field(default_factory=set)


def normalize_numbers(text: str) -> set[float]:
    """Extract numeric facts, expanding ``N万`` to N*10000.

    ``12.5万`` → 125000（小数万已覆盖，规格表里多写 ``12.5万`` 或 ``125000``）。
    口语化的 ``12万5``（=125000）不做合并，会得到 {120000, 5}；本域规格不用
    这种写法，故不处理（注入/成稿两侧用同一函数，对称不致误判）。
    """
    out: set[float] = set()
    consumed: list[tuple[int, int]] = []
    for m in _WAN_RE.finditer(text):
        out.add(float(m.group(1)) * 10000)
        consumed.append(m.span())
    for m in _NUM_RE.finditer(text):
        # m.span() 覆盖 "12万"：跳过 万 表达式内部的 "12" 裸数字，避免混入 12.0。
        if any(s <= m.start() < e for s, e in consumed):
            continue
        out.add(float(m.group()))
    return out


def build_fact_whitelist(
    memory: BrandModelMemory, injected_texts: list[str],
) -> FactWhitelist:
    numbers: set[float] = set()
    for sv in memory.specs.values():
        numbers.update(sv.numbers)
    for text in injected_texts:
        numbers.update(normalize_numbers(text))
    return FactWhitelist(numbers=numbers, certs=set(memory.certs))
