"""Extract the *core product term* from a long-tail SEO keyword.

User SEO keywords typically look like::

    [时效前缀]?  核心产品词  [问句/决策/评测尾巴]?

For example::

    "2026年无线吸尘器哪款好用"  →  "无线吸尘器"
    "扫地机器人值得买吗"        →  "扫地机器人"
    "家用空气净化器推荐"         →  "家用空气净化器"
    "吸尘器"                     →  "吸尘器"   (no edges to strip)

This module strips known tail / lead phrases and returns the core term.
The pipeline uses the core for in-article ``{keyword}`` substitution
(段落标题、产品卡片) while keeping the long-tail original for the SEO
title — separating those two roles fixes awkward strings like
"CEWEY DS18 无线吸尘器哪款好用" or "无线吸尘器哪款好用应该怎么选?".

Extending the dictionary
------------------------
Just add the new tail/prefix to the literal lists below — they're sorted
**longest-first** so multi-character matches win over their substrings
("哪款好用" beats "好用" beats "用").
"""
from __future__ import annotations
import re

# ── Right-side tails (decision / evaluation / pricing phrases) ─────────
# These are stripped from the **end** of the keyword. Order matters —
# longer phrases first, otherwise "好用" eats "哪款好用" before we see it.
_RAW_TAILS = [
    # 决策类
    "哪款好用", "哪款最好", "哪款值得买", "哪款好",
    "哪个好用", "哪个最好", "哪个值得买", "哪个好",
    "哪种好用", "哪种最好", "哪种好",
    "怎么选", "怎么挑", "怎么样", "怎么用", "好用吗", "好不好", "好用",
    "选哪款", "选哪个", "选哪种",
    # "哪款 / 哪个 / 哪种" 单独残留（出现在多层剥离后）
    "哪款", "哪个", "哪种",
    # 评测 / 排行 / 对比
    "推荐", "测评", "评测", "排行榜", "排行", "排名",
    "盘点", "对比", "区别", "差别", "性价比",
    "什么牌子好", "什么牌子", "哪个牌子好", "哪个牌子", "哪个品牌",
    # 价格类
    "多少钱", "价格", "便宜", "贵不贵", "贵吗",
    # 杂项问句
    "吗", "呢",  # 兜底问号尾，避免漏网
]
TAIL_PATTERNS: list[str] = sorted(_RAW_TAILS, key=len, reverse=True)

# ── Left-side leading prefixes (年份 / 时效 / 修饰) ────────────────────
# Stripped from the **start**. Year prefixes are matched as a regex so we
# don't have to enumerate every year.
_RAW_LEADS = [
    "今年最新", "今年最热", "今年", "最新", "最热",
    "入手前必看", "新手必看", "小白必看",
]
LEADING_PATTERNS: list[str] = sorted(_RAW_LEADS, key=len, reverse=True)

# 年份前缀：2024年 / 2025年 / 2026年 / ... + 可选的 "上半年"/"下半年" 等。
# 不维护静态列表，避免每年漏更新。
_YEAR_PREFIX_RE = re.compile(r"^(?:19|20)\d{2}\s*年(?:上半年|下半年|初|底)?\s*")

# Trailing punctuation 通常没有意义，剥掉。
_TRAILING_PUNCT_RE = re.compile(r"[,，.。?？!！\s]+$")


# 抽取后剩余字符若少于这个长度，认为提取失败（误剥），回退到原 keyword。
MIN_CORE_LENGTH = 2


def _strip_one_tail(s: str) -> tuple[str, bool]:
    """Try to strip a single tail pattern. Returns (new_s, did_strip)."""
    for tail in TAIL_PATTERNS:
        if s.endswith(tail) and len(s) > len(tail):
            return s[: -len(tail)], True
    return s, False


def _strip_one_lead(s: str) -> tuple[str, bool]:
    """Try to strip a single leading pattern. Returns (new_s, did_strip)."""
    # Year prefix takes priority over fixed strings.
    m = _YEAR_PREFIX_RE.match(s)
    if m and len(s) > m.end():
        return s[m.end():], True
    for lead in LEADING_PATTERNS:
        if s.startswith(lead) and len(s) > len(lead):
            return s[len(lead):], True
    return s, False


def extract_core(keyword: str) -> str:
    """Strip SEO tails / leading prefixes to recover the core product term.

    Idempotent — running it on an already-clean keyword returns the
    keyword unchanged. Falls back to the original input when stripping
    would leave less than :data:`MIN_CORE_LENGTH` characters.

    Examples
    --------
    >>> extract_core("无线吸尘器哪款好用")
    '无线吸尘器'
    >>> extract_core("2026年家用空气净化器推荐")
    '家用空气净化器'
    >>> extract_core("吸尘器")
    '吸尘器'
    >>> extract_core("")
    ''
    """
    if not keyword:
        return ""
    original = keyword.strip()
    if not original:
        return ""

    s = original
    s = _TRAILING_PUNCT_RE.sub("", s)

    # Iteratively strip until nothing matches. Hard cap to avoid pathological
    # loops (which shouldn't happen given len-decreasing invariants, but
    # belt-and-suspenders).
    for _ in range(10):
        s, did_lead = _strip_one_lead(s)
        s, did_tail = _strip_one_tail(s)
        s = _TRAILING_PUNCT_RE.sub("", s).strip()
        if not (did_lead or did_tail):
            break

    if len(s) < MIN_CORE_LENGTH:
        # Stripping was too aggressive — fall back to original.
        return original
    return s
