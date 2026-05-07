"""Character-level shingling for dedup detection.

The default ``n=13`` matches what most Chinese plagiarism-detection systems
use — small enough to catch sentence-level reuse, large enough that a
13-char window appearing in two unrelated documents is overwhelmingly
unlikely to be coincidence.

For LSH candidate retrieval, ``compute_shingles`` returns a flat set.
For precise overlap location (drill-down UI), use ``compute_shingles_with_positions``
which keeps the start index of each occurrence.
"""
from __future__ import annotations

DEFAULT_N = 13


def compute_shingles(text: str, n: int = DEFAULT_N) -> set[str]:
    """Return the set of all n-character substrings of ``text``.

    Empty or shorter-than-n inputs return an empty set rather than raising.
    """
    if not text or len(text) < n:
        return set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def compute_shingles_with_positions(
    text: str, n: int = DEFAULT_N,
) -> dict[str, list[int]]:
    """Return a dict mapping each n-shingle to the list of start indices
    (in character units) where it appears in ``text``.

    Used for the drill-down precise pass: given a candidate doc's shingle
    set, we find which positions in ``text`` are covered by matching shingles.
    """
    out: dict[str, list[int]] = {}
    if not text or len(text) < n:
        return out
    for i in range(len(text) - n + 1):
        s = text[i:i + n]
        out.setdefault(s, []).append(i)
    return out
