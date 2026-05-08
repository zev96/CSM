"""Dedup report data structures."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SegmentHit:
    """One contiguous span in the analyzed text covered by candidate shingles."""
    start: int
    end: int
    text: str
    source_path: str
    source_title: str
    source_excerpt: str


@dataclass
class TopMatch:
    """Aggregate stats for one source document that overlapped current text."""
    source_path: str
    source_title: str
    overlap_chars: int
    overlap_ratio: float


@dataclass
class DuplicateReport:
    """Result of analyzing one text against one corpus.

    ``corpus_kind`` is "history" or "vault" — the UI shows two reports side
    by side (one per kind).
    """
    corpus_kind: str
    text_length: int
    duplicate_chars: int
    duplicate_ratio: float
    top_matches: list[TopMatch] = field(default_factory=list)
    hits: list[SegmentHit] = field(default_factory=list)
    computed_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def empty(cls, kind: str) -> "DuplicateReport":
        """Empty report — used by the UI when index is missing or text too short."""
        return cls(
            corpus_kind=kind,
            text_length=0,
            duplicate_chars=0,
            duplicate_ratio=0.0,
        )
