"""禁区 lint 扫描 + 一键清。纯函数。"""
from __future__ import annotations
import re

from .model import LintHit, LintReport
from .rules import DASH_PATTERN, EMOJI_PATTERN, QUOTE_CHARS, Rules

_SENT_BOUND = set("。！？!?\n")
_PRIORITY = {"meta_speak": 0, "absolute": 1, "traffic": 2, "emoji": 3, "dash": 4, "quote": 5}

_SUGGEST = {
    "meta_speak": "删除或改写：避免「广告/推广/软文」等元话术",
    "absolute": "改为非绝对化表述（避开 最/第一/100% 等极限词）",
    "traffic": "删除引流话术（平台违规）",
    "emoji": "删除 emoji",
    "dash": "改为逗号或删除",
    "quote": "删除双引号（保留内文）",
}


def _sentence_at(text: str, pos: int, cap: int = 80) -> str:
    start = pos
    while start > 0 and text[start - 1] not in _SENT_BOUND:
        start -= 1
    end = pos
    while end < len(text) and text[end] not in _SENT_BOUND:
        end += 1
    return text[start:end].strip()[:cap]


# (start, end, text, category, fixable)
def _word_hits(text, words, category):
    out = []
    for w in words:
        i = text.find(w)
        while i != -1:
            out.append((i, i + len(w), w, category, False))
            i = text.find(w, i + 1)
    return out


def scan(text: str, rules: Rules) -> list[LintHit]:
    raw: list[tuple] = []
    raw += _word_hits(text, rules.meta, "meta_speak")
    raw += _word_hits(text, rules.absolute, "absolute")
    raw += _word_hits(text, rules.traffic, "traffic")
    if rules.check_emoji:
        raw += [(m.start(), m.end(), m.group(), "emoji", True) for m in EMOJI_PATTERN.finditer(text)]
    if rules.check_dash:
        raw += [(m.start(), m.end(), m.group(), "dash", True) for m in DASH_PATTERN.finditer(text)]
    if rules.check_quote:
        raw += [(i, i + 1, ch, "quote", True) for i, ch in enumerate(text) if ch in QUOTE_CHARS]

    # 排序：起点升序 → 长度降序 → 优先级。贪心取不重叠（最长/最高优先覆盖）。
    raw.sort(key=lambda h: (h[0], -(h[1] - h[0]), _PRIORITY[h[3]]))
    chosen, occupied_end = [], -1
    for h in raw:
        if h[0] >= occupied_end:
            chosen.append(h)
            occupied_end = h[1]
    chosen.sort(key=lambda h: h[0])
    return [
        LintHit(category=c, text=t, start=s, end=e,
                sentence=_sentence_at(text, s), fixable=f, suggestion=_SUGGEST[c])
        for (s, e, t, c, f) in chosen
    ]


def autofix(text: str, rules: Rules) -> str:
    """只清机械三类：emoji 删 / 破折号→逗号 / 双引号删（保留内文）。判断类不动。幂等。"""
    t = text
    if rules.check_emoji:
        t = EMOJI_PATTERN.sub("", t)
    if rules.check_dash:
        t = DASH_PATTERN.sub("，", t)
        t = re.sub("，{2,}", "，", t)            # 合并连续逗号
        t = re.sub(r"([。！？!?])，", r"\1", t)   # 句末标点后多余逗号去掉
    if rules.check_quote:
        t = "".join(ch for ch in t if ch not in QUOTE_CHARS)
    return t


def build_report(text: str, rules: Rules) -> LintReport:
    return LintReport(hits=scan(text, rules), fixed_text=autofix(text, rules))
