"""Parse a single Obsidian markdown note into frontmatter + variant sections."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
import frontmatter

VARIANT_MARKERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")
_VARIANT_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨]\s*", re.MULTILINE)


@dataclass
class ParsedNote:
    path: Path
    id: str
    frontmatter: dict[str, Any]
    variants: list[str] = field(default_factory=list)
    raw_body: str = ""


def parse_note(path: Path) -> ParsedNote:
    post = frontmatter.load(str(path))
    body = post.content.strip()
    variants = _split_variants(body)
    return ParsedNote(
        path=path,
        id=path.stem,
        frontmatter=dict(post.metadata),
        variants=variants,
        raw_body=body,
    )


def _split_variants(body: str) -> list[str]:
    """Split body on lines starting with ①/②/③/... Returns list of variant texts.

    If no numbered markers found, returns [body] as single variant.
    """
    if not any(marker in body for marker in VARIANT_MARKERS):
        return [body] if body else []

    # Split on lines starting with a variant marker
    parts: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped and stripped[0] in VARIANT_MARKERS:
            if current:
                parts.append("\n".join(current).strip())
                current = []
            current.append(_VARIANT_RE.sub("", line, count=1))
        else:
            current.append(line)
    if current:
        tail = "\n".join(current).strip()
        if tail:
            parts.append(tail)
    return [p for p in parts if p]
