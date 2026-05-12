"""Keyword density — pure sidecar adapter, no csm_core involvement.

Used by the article 质检报告 card. Two outputs:

* ``count`` — exact (case-sensitive) substring occurrences of the keyword
* ``density`` — count × len(keyword) / len(text), as a ratio in [0, 1]

We deliberately don't tokenise — Chinese keywords don't have whitespace
boundaries and a substring count tracks closer to what users expect from
"出现次数" in the UI. Case is preserved as-is.
"""
from __future__ import annotations


def density(*, text: str, keyword: str) -> dict[str, float | int]:
    text = text or ""
    keyword = keyword or ""
    if not keyword:
        return {"count": 0, "density": 0.0, "text_length": len(text), "keyword_length": 0}
    if not text:
        return {"count": 0, "density": 0.0, "text_length": 0, "keyword_length": len(keyword)}

    # Sliding-window count of overlapping occurrences would inflate the
    # number for repeated chars (e.g. "aaa" with keyword "aa" → 2). We
    # use non-overlapping count via str.count, which matches what the
    # GUI 字数 panel showed.
    count = text.count(keyword)
    coverage = count * len(keyword)
    return {
        "count": count,
        "density": round(coverage / len(text), 6),
        "text_length": len(text),
        "keyword_length": len(keyword),
    }
