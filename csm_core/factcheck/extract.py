"""Extract checkable facts (parameter numbers + cert names) from text.

只抽带**参数单位**的数字（250AW / 35kPa / 12万转 / 60%）；裸数字与计数词
（3款 / 第1名 / 2024年）不是参数，跳过 —— 这是防误拦（验收 #4）的核心。
``万`` 展开为 ×10000，与 brand_memory.whitelist.normalize_numbers 对称，
保证白名单（用同一份源文本构建）与核对口径一致。本模块**不依赖
brand_memory**（避免循环导入）。
"""
from __future__ import annotations
import re

# 计量单位词表（measurement units only —— 不含 款/项/档 等计数词）。
# 长单位在前：让 "AW" 先于 "W"、"kPa" 先于 "Pa"、"L/min" 先于 "L" 命中。
UNITS: tuple[str, ...] = (
    "L/min", "mmH2O", "mAh", "kWh", "kPa", "KPa", "rpm",
    "Wh", "kW", "AW", "Pa", "dB", "mL", "ml", "μm", "um",
    "nm", "mm", "cm", "kg", "min", "转", "倍", "元",
    "W", "L", "g", "h", "%",
)
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
_NUM_UNIT_RE = re.compile(rf"(\d+(?:\.\d+)?)\s*(万)?\s*({_UNIT_ALT})")

# 认证名词表（大写、词界匹配）。常见家电认证。
CERT_VOCAB: tuple[str, ...] = (
    "RoHS", "CCC", "FCC", "CQC", "PSE", "ETL", "SGS",
    "CE", "CB", "UL", "GS", "3C",
)
_CERT_ALT = "|".join(re.escape(c) for c in sorted(CERT_VOCAB, key=len, reverse=True))
_CERT_RE = re.compile(rf"(?<![A-Za-z0-9])({_CERT_ALT})(?![A-Za-z0-9])")

_SENT_SPLIT_RE = re.compile(r"[。！？!?\n；;]+")


def _value(num: str, wan: str | None) -> float:
    return float(num) * (10000.0 if wan else 1.0)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def extract_number_mentions(text: str) -> list[tuple[float, str]]:
    """[(归一值, 原文 token)]，仅限带参数单位的数字。"""
    return [
        (_value(m.group(1), m.group(2)), m.group(0).strip())
        for m in _NUM_UNIT_RE.finditer(text or "")
    ]


def extract_certs(text: str) -> list[str]:
    """文本里出现的认证名（去重、保序）。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in _CERT_RE.finditer(text or ""):
        c = m.group(1)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
