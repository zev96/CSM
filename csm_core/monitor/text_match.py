"""Comment-similarity matching, ported from Case-8.

The original Case-8 ``text_matcher.py`` was nearly self-contained — this
file keeps the same algorithm (normalize → SequenceMatcher.ratio) so any
behavior validated in Case-8 carries over, but exposes a flat function
API instead of a class so adapters can call it without instantiation.

Why SequenceMatcher and not e.g. cosine on tf-idf: comments are short
(<200 chars), the matching question is "did this exact comment land in
the hot list", and ratio() is robust to the trivial edits Bilibili /
Douyin sometimes apply (trailing whitespace, punctuation normalization).
The 0.85 threshold is the value Case-8 ran in production.
"""
from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Any, Iterable, TypedDict


DEFAULT_SIMILARITY_THRESHOLD = 0.85


class MatchResult(TypedDict):
    found: bool
    rank: int
    matched_text: str | None
    similarity: float
    normalized_target: str
    normalized_match: str | None
    threshold_used: float


# Ranges kept as a module-level constant so the regex is compiled once.
# CJK ideographs + ASCII letters + digits is enough for our platforms;
# emoji are stripped because Bilibili strips them in some surfaces but
# not others, which would otherwise tank ratio() unfairly.
_NORMALIZE_RE = re.compile(r"[^一-鿿a-z0-9]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Lower-case, strip whitespace, drop everything but CJK/ASCII alnum."""
    if not text:
        return ""
    text = text.lower()
    text = _WHITESPACE_RE.sub("", text)
    text = _NORMALIZE_RE.sub("", text)
    return text


def calculate_similarity(text1: str | None, text2: str | None) -> float:
    """0.0–1.0 ratio between two texts, post-normalization."""
    n1, n2 = normalize_text(text1), normalize_text(text2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def find_best_match(
    target_text: str,
    comment_list: Iterable[dict[str, Any]],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> MatchResult:
    """Return the best matching comment + its rank, or a "not found" record.

    ``comment_list`` items must have ``text`` and ``rank`` keys (extra
    fields are ignored). Rank is taken from the comment dict, not from
    the iteration order — adapters that page through the API must set
    each comment's ``rank`` correctly before calling this.
    """
    out: MatchResult = {
        "found": False,
        "rank": -1,
        "matched_text": None,
        "similarity": 0.0,
        "normalized_target": normalize_text(target_text),
        "normalized_match": None,
        "threshold_used": threshold,
    }
    if not target_text:
        return out
    best_sim = 0.0
    for comment in comment_list:
        text = comment.get("text", "")
        if not text:
            continue
        sim = calculate_similarity(target_text, text)
        if sim > best_sim:
            best_sim = sim
            out["similarity"] = sim
            out["matched_text"] = text
            out["rank"] = int(comment.get("rank", -1))
            out["normalized_match"] = normalize_text(text)
    if best_sim >= threshold:
        out["found"] = True
    return out


def match_in_range(
    target_text: str,
    comment_list: list[dict[str, Any]],
    start: int = 0,
    end: int | None = None,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> MatchResult:
    """Convenience: only consider a slice of the comment list."""
    if end is None:
        end = len(comment_list)
    return find_best_match(target_text, comment_list[start:end], threshold)
