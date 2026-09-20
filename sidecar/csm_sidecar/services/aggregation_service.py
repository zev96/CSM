"""Aggregation views — sidecar-only adapters that turn the contents of
``dedup_history_dir`` into the shape the home screen's 最近文档 card and
the /recent-history list expect.

This doesn't belong in csm_core because it's UI-shaped (recent-doc cards)
— the underlying data is just the markdown mirrors on disk that earlier
versions exported into the history dir.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import frontmatter

from . import config_service

logger = logging.getLogger(__name__)


# ── Recent docs (home screen) ──────────────────────────────────────────────
def list_recent(*, limit: int = 5, days: int = 7) -> dict[str, Any]:
    """Return recent .md files under ``dedup_history_dir``, newest first."""
    history_dir = _resolve_history_dir()
    if history_dir is None or not history_dir.exists():
        return {"count": 0, "documents": []}
    cutoff = datetime.now() - timedelta(days=days)
    items: list[dict[str, Any]] = []
    for f in _iter_exported(history_dir):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        items.append({
            "path": str(f),
            "filename": f.name,
            "title": _doc_title(f),
            "template_name": _doc_template_name(f),
            "words": _doc_word_count(f),
            "modified_at": mtime.isoformat(),
            "format": "markdown",
        })
    items.sort(key=lambda d: d["modified_at"], reverse=True)
    top = items[:limit]
    return {"count": len(top), "documents": top}


def _doc_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    try:
        post = frontmatter.loads(text)
        if post.metadata.get("title"):
            return str(post.metadata["title"])
        return extract_title(post.content) or path.stem
    except Exception:
        return extract_title(text) or path.stem


def _doc_template_name(path: Path) -> str | None:
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except (OSError, Exception):  # noqa: BLE001 — robustness
        return None
    return post.metadata.get("template") or post.metadata.get("template_name")


def _doc_word_count(path: Path) -> int:
    """Rough character count for the article body (Chinese-friendly)."""
    try:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        return _count_chars(post.content)
    except Exception:
        return 0


def _count_chars(text: str) -> int:
    """Char count excluding whitespace and markdown punctuation. Matches
    what the legacy GUI 字数 panel showed."""
    return sum(1 for c in (text or "") if not c.isspace() and c not in "*#`>-_")


# ── Markdown title helpers (inlined from the retired csm_core.export) ──────
def _heading_level(line: str) -> tuple[int, str] | None:
    """Return (level, text) for a markdown heading line, else None."""
    m = re.match(r"^(#{1,6})\s+(.*)$", line)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def extract_title(text: str) -> str:
    """Pull the first heading line from a markdown document.

    Used by the home-page recents to show the article's headline rather
    than the on-disk filename. Falls back to the first non-empty prose
    line if no headings exist; returns "" if the document is empty.
    """
    first_prose = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        h = _heading_level(line)
        if h is not None and h[1]:
            return h[1]
        if not first_prose:
            first_prose = line
    return first_prose


# ── Helpers ────────────────────────────────────────────────────────────────
def _resolve_history_dir() -> Path | None:
    """Source-of-truth folder for 'recent docs'.

    Switched from ``out_dir`` to ``dedup_history_dir`` in 0.5.0 — the
    history dir holds .md mirrors of every export and is the only place
    the home screen needs to scan. See:
    docs/superpowers/specs/2026-05-12-recent-history-and-vault-attrs-design.md
    """
    cfg = config_service.load()
    return Path(cfg.dedup_history_dir) if cfg.dedup_history_dir else None


def _iter_exported(history_dir: Path):
    """Yield every .md under ``history_dir`` (recursive). Skips hidden files.

    History dir mirrors are .md only; we deliberately ignore .docx so a
    stray docx the user dropped in there doesn't pollute aggregations.
    """
    for p in history_dir.rglob("*.md"):
        if p.name.startswith("."):
            continue
        yield p
