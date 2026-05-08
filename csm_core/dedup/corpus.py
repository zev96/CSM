"""Corpus scanning + text extraction.

Supports ``.md``, ``.txt``, ``.docx``. Files over ``MAX_FILE_BYTES`` are
skipped (defensive — a 50MB markdown is almost certainly garbage). The
scanner yields one ``CorpusEntry`` per supported file under the root,
recursively.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".md", ".txt", ".docx")
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class CorpusEntry:
    """One scanned source file + its extracted text + mtime for incremental update."""
    path: Path
    title: str
    text: str
    mtime: float


def extract_text(path: Path) -> str:
    """Extract plain-text content from a supported file. Returns "" on failure."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".md", ".txt"):
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".docx":
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception as exc:
        logger.warning("dedup corpus: failed to read %s — %s", path, exc)
        return ""
    return ""


def extract_title(path: Path) -> str:
    """Best-effort title extraction.

    For ``.md``: first H1 line; falls back to file stem.
    For ``.txt``/``.docx``: file stem.
    """
    if path.suffix.lower() == ".md":
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            m = _H1_RE.search(content)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
    return path.stem


def scan_corpus(root: Path) -> Iterator[CorpusEntry]:
    """Yield CorpusEntry for every supported file under ``root`` (recursive).

    Silently skips:
    - non-existent root
    - files exceeding MAX_FILE_BYTES
    - files where text extraction returns empty
    """
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > MAX_FILE_BYTES:
            logger.info("dedup corpus: skipping oversize file %s (%d bytes)",
                        path, stat.st_size)
            continue
        text = extract_text(path)
        if not text.strip():
            continue
        yield CorpusEntry(
            path=path,
            title=extract_title(path),
            text=text,
            mtime=stat.st_mtime,
        )
