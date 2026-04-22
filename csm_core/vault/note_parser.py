"""Parse a single Obsidian markdown note into frontmatter + variant sections."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
import frontmatter

VARIANT_MARKERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")
# Match a variant marker at the start of a line, tolerating leading whitespace
# and an optional ATX heading prefix (``### ① ...``) so heading-wrapped
# markers are stripped along with bare ones.
_VARIANT_RE = re.compile(
    r"^\s*(?:#{1,6}\s+)?[①②③④⑤⑥⑦⑧⑨]\s*", re.MULTILINE,
)
# Same pattern without the trailing ``\s*`` — used to *detect* a variant-start
# line (independent of splitting), so ``_split_variants`` recognises e.g.
# ``### ① 噪音控制水平`` as a variant boundary.
_VARIANT_START_RE = re.compile(r"^\s*(?:#{1,6}\s+)?[①②③④⑤⑥⑦⑧⑨]")
# Inline bold (``**text**``). Kept conservative: no newlines, non-greedy, at
# least one inner char. The inner text survives; the ``**`` markers are peeled
# off so drafts render as plain prose.
_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
# Horizontal-rule lines (``---`` / ``***`` / ``___``): vault notes sometimes
# put a stray ``---`` between the last variant and the backlink tail, and it
# would otherwise be rendered as a horizontal rule mid-draft.
_HR_LINE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
# ATX heading markers (``### Foo``): drop the ``#``s but keep the text so the
# sentence survives as plain prose instead of an unwanted subheading.
_HEADING_PREFIX_RE = re.compile(r"^\s*#{1,6}\s+")
# Any of these on a line marks the start of the vault's navigation/backlink
# tail. Supported styles:
#   ← 返回: [[索引]]                        (arrow style)
#   **返回上层**: [[引言模块总索引|…]]        (bold label)
#   **返回主页**: 关联数据库                  (bold label)
#   返回上层: …   /   返回主页: …             (naked label)
#   相关笔记                                   (section header that follows)
_BACKLINK_LINE_RE = re.compile(
    r"(?:←\s*返回|\*\*返回(?:上层|主页)\*\*\s*[:：]|"
    r"^\s*返回(?:上层|主页)\s*[:：]|^\s*相关笔记\s*$)"
)


@dataclass
class ParsedNote:
    path: Path
    id: str
    frontmatter: dict[str, Any]
    variants: list[str] = field(default_factory=list)
    raw_body: str = ""


def _strip_backlinks(body: str) -> str:
    """Drop the Obsidian navigation / backlink tail from ``body``.

    Returns ``body`` up to (but excluding) the first line that matches any of
    the styles listed in ``_BACKLINK_LINE_RE``. See that regex for the exact
    markers. Everything from that line onward is considered navigation chrome
    and must not leak into generated drafts.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if _BACKLINK_LINE_RE.search(line):
            return "\n".join(lines[:i]).rstrip()
    return body


def parse_note(path: Path) -> ParsedNote:
    # Read as utf-8-sig so a leading UTF-8 BOM is stripped before parsing.
    # python-frontmatter's ``load`` reads raw bytes and does not remove the
    # BOM itself — with one in place, the opening ``---`` is no longer at the
    # start of the stream and frontmatter is silently dropped.
    text = Path(path).read_text(encoding="utf-8-sig")
    post = frontmatter.loads(text)
    body = _strip_backlinks(post.content.strip())
    variants = _split_variants(body)
    return ParsedNote(
        path=path,
        id=path.stem,
        frontmatter=dict(post.metadata),
        variants=variants,
        raw_body=body,
    )


def _clean_chrome(text: str) -> str:
    """Strip markdown chrome (horizontal rules, heading prefixes) from ``text``.

    Horizontal-rule lines (``---``/``***``/``___``) are dropped entirely.
    ATX heading markers (``###``) are removed but the heading text is kept,
    so a ``### 产品优势`` line survives as plain ``产品优势``.
    """
    out: list[str] = []
    for line in text.splitlines():
        if _HR_LINE_RE.match(line):
            continue
        line = _HEADING_PREFIX_RE.sub("", line)
        line = _BOLD_RE.sub(r"\1", line)
        # Strip any residual ①②③ markers that weren't at column 0 (e.g. nested
        # sub-lists inside a variant body); keeps the text that follows.
        line = _VARIANT_RE.sub("", line)
        out.append(line)
    return "\n".join(out).strip()


def _split_variants(body: str) -> list[str]:
    """Split body on lines starting with ①/②/③/... Returns list of variant texts.

    If no numbered markers found, returns [body] as single variant.
    """
    if not any(marker in body for marker in VARIANT_MARKERS):
        cleaned = _clean_chrome(body)
        return [cleaned] if cleaned else []

    # Split on lines starting with a variant marker — either bare (``① ...``)
    # or wrapped in an ATX heading (``### ① ...``). The regex handles both.
    parts: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if _VARIANT_START_RE.match(line):
            if current:
                parts.append(_clean_chrome("\n".join(current)))
                current = []
            current.append(_VARIANT_RE.sub("", line, count=1))
        else:
            current.append(line)
    if current:
        tail = _clean_chrome("\n".join(current))
        if tail:
            parts.append(tail)
    return [p for p in parts if p]
