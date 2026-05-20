"""Dedup analyzer: build index from corpus, analyze text against it.

Two-stage analysis:
1. LSH candidate retrieval (top-K most-similar docs by Jaccard estimate)
2. Per-candidate precise overlap (shingle position intersection → covered
   character bitmap → SegmentHit list + per-source TopMatch totals)
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from .corpus import scan_corpus
from .index import DedupIndex
from .report import DuplicateReport, SegmentHit, TopMatch
from .shingles import (
    DEFAULT_N, compute_shingles, compute_shingles_with_positions,
)

logger = logging.getLogger(__name__)

MIN_ANALYZABLE_CHARS = 50
TOP_MATCHES_RETURNED = 3
TOP_K_CANDIDATES = 10
EXCERPT_CONTEXT = 50


def build_doc_id(path: Path) -> str:
    """Deterministic short id from absolute path."""
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


class DedupAnalyzer:
    """Owns one index per ``kind`` (e.g. "history", "vault")."""

    def __init__(self):
        self._indexes: dict[str, DedupIndex] = {}

    # ── Index management ───────────────────────────────────────────────
    def build_index(
        self,
        root: Path,
        *,
        kind: str,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        """Walk ``root`` and build a fresh DedupIndex under ``kind``."""
        # Pre-count for progress
        total = sum(1 for _ in scan_corpus(root))
        if total == 0:
            self._indexes[kind] = DedupIndex()
            if progress_cb:
                progress_cb(0, 0)
            return

        idx = DedupIndex()
        done = 0
        for entry in scan_corpus(root):
            doc_id = build_doc_id(entry.path)
            idx.add_doc(
                doc_id,
                entry.text,
                meta={
                    "path": str(entry.path),
                    "title": entry.title,
                    "mtime": entry.mtime,
                },
            )
            done += 1
            if progress_cb and done % 10 == 0:
                progress_cb(done, total)
        if progress_cb:
            progress_cb(done, total)
        self._indexes[kind] = idx

    def index_doc_count(self, kind: str) -> int:
        idx = self._indexes.get(kind)
        return idx.doc_count() if idx else 0

    def save(self, dir_path: Path) -> None:
        for kind, idx in self._indexes.items():
            idx.save(dir_path, name=kind)

    def load(self, dir_path: Path, *, kinds: tuple[str, ...] = ("history", "vault")) -> None:
        for kind in kinds:
            self._indexes[kind] = DedupIndex.load(dir_path, name=kind)

    # ── Analysis ───────────────────────────────────────────────────────
    def analyze(self, text: str, *, kind: str) -> DuplicateReport:
        """Analyze ``text`` against the index for ``kind``."""
        if kind not in self._indexes:
            return DuplicateReport.empty(kind)
        if len(text) < MIN_ANALYZABLE_CHARS:
            return DuplicateReport.empty(kind)

        idx = self._indexes[kind]
        candidates = idx.query(text, top_k=TOP_K_CANDIDATES)
        if not candidates:
            return DuplicateReport(
                corpus_kind=kind,
                text_length=len(text),
                duplicate_chars=0,
                duplicate_ratio=0.0,
                top_matches=[],
                hits=[],
                computed_at=datetime.now(),
            )

        current_pos = compute_shingles_with_positions(text)
        if not current_pos:
            return DuplicateReport.empty(kind)

        # Per-position attribution: which doc covers position i?
        # First candidate (in candidates order) whose shingle covers i wins.
        covered = bytearray(len(text))
        attribution: dict[int, str] = {}
        per_doc_chars: dict[str, int] = {}

        for doc_id in candidates:
            doc_meta = idx.get_meta(doc_id) or {}
            doc_path = doc_meta.get("path", "")
            if not doc_path:
                continue
            try:
                if doc_path.lower().endswith(".docx"):
                    from .corpus import extract_text
                    cand_text = extract_text(Path(doc_path))
                else:
                    cand_text = Path(doc_path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            cand_shingles = compute_shingles(cand_text)
            if not cand_shingles:
                continue

            doc_chars = 0
            for shingle, positions in current_pos.items():
                if shingle not in cand_shingles:
                    continue
                for pos in positions:
                    for j in range(pos, min(pos + DEFAULT_N, len(text))):
                        if not covered[j]:
                            covered[j] = 1
                            attribution[j] = doc_id
                            doc_chars += 1
            per_doc_chars[doc_id] = per_doc_chars.get(doc_id, 0) + doc_chars

        duplicate_chars = sum(covered)
        text_length = len(text)
        ratio = duplicate_chars / text_length if text_length else 0.0

        ranked = sorted(per_doc_chars.items(), key=lambda kv: kv[1], reverse=True)
        top_matches: list[TopMatch] = []
        for doc_id, chars in ranked[:TOP_MATCHES_RETURNED]:
            meta = idx.get_meta(doc_id) or {}
            top_matches.append(TopMatch(
                source_path=meta.get("path", ""),
                source_title=meta.get("title", ""),
                overlap_chars=chars,
                overlap_ratio=chars / text_length if text_length else 0.0,
            ))

        # Build SegmentHit list — collapse runs of consecutive covered positions.
        # Cache loaded source files: a single source typically covers several
        # disjoint regions, and we'd otherwise re-open + decode the same file
        # once per hit. Also mirrors the .docx branch from the candidates loop
        # so excerpts from binary .docx sources actually populate.
        hits: list[SegmentHit] = []
        src_text_cache: dict[str, str] = {}

        def _src_text(p: str) -> str:
            if p in src_text_cache:
                return src_text_cache[p]
            loaded = ""
            try:
                if p.lower().endswith(".docx"):
                    from .corpus import extract_text
                    loaded = extract_text(Path(p))
                else:
                    loaded = Path(p).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                loaded = ""
            src_text_cache[p] = loaded
            return loaded

        i = 0
        while i < len(covered):
            if covered[i]:
                j = i
                while j < len(covered) and covered[j]:
                    j += 1
                doc_id = attribution.get(i, "")
                meta = idx.get_meta(doc_id) or {}
                src_path = meta.get("path", "")
                excerpt = ""
                if src_path:
                    src_text = _src_text(src_path)
                    if src_text:
                        seg = text[i:j]
                        idx_in_src = src_text.find(seg)
                        if idx_in_src >= 0:
                            lo = max(0, idx_in_src - EXCERPT_CONTEXT)
                            hi = min(len(src_text), idx_in_src + len(seg) + EXCERPT_CONTEXT)
                            excerpt = src_text[lo:hi]
                hits.append(SegmentHit(
                    start=i, end=j,
                    text=text[i:j],
                    source_path=src_path,
                    source_title=meta.get("title", ""),
                    source_excerpt=excerpt,
                ))
                i = j
            else:
                i += 1

        return DuplicateReport(
            corpus_kind=kind,
            text_length=text_length,
            duplicate_chars=duplicate_chars,
            duplicate_ratio=ratio,
            top_matches=top_matches,
            hits=hits,
            computed_at=datetime.now(),
        )
