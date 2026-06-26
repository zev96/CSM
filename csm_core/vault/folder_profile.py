"""Infer what shape to write into a vault folder from its existing notes.

The vault is the source of truth (CLAUDE.md has drifted), so the intake form
mirrors a target folder's existing notes rather than a hardcoded taxonomy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .note_parser import ParsedNote, VARIANT_MARKERS
from .scanner import VaultIndex

_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_LEAD_KEYS = ("产品", "素材类型", "核心关键词")


@dataclass(frozen=True)
class FolderProfile:
    rel_folder: str
    frontmatter_keys: list[str] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)
    body_shape: str = "unknown"          # "variants" | "spec_table" | "unknown"
    sample_count: int = 0
    material_types: list[str] = field(default_factory=list)


def _rel_folder_of(note: ParsedNote, root) -> str | None:
    try:
        parts = note.path.relative_to(root).parts[:-1]
    except ValueError:
        return None
    return "/".join(parts)


def _is_variants(note: ParsedNote) -> bool:
    if len(note.variants) >= 2:
        return True
    return any(m in note.raw_body for m in VARIANT_MARKERS)


def _is_spec_table(note: ParsedNote) -> bool:
    return len(_TABLE_RE.findall(note.raw_body)) >= 2


def profile_folder(index: VaultIndex, rel_folder: str) -> FolderProfile:
    notes = [n for n in index.notes if _rel_folder_of(n, index.root) == rel_folder]
    if not notes:
        return FolderProfile(rel_folder=rel_folder)

    # frontmatter keys: union preserving order, lead keys first.
    seen: dict[str, None] = {}
    for n in notes:
        for k in (n.frontmatter or {}):
            seen.setdefault(k, None)
    keys = [k for k in _LEAD_KEYS if k in seen] + [k for k in seen if k not in _LEAD_KEYS]

    # defaults: scalar key whose value is identical across ≥ half the notes.
    defaults: dict[str, str] = {}
    for k in keys:
        vals = [str(n.frontmatter[k]) for n in notes
                if k in n.frontmatter and not isinstance(n.frontmatter[k], list)]
        if vals and vals.count(vals[0]) * 2 >= len(notes) and len(set(vals)) == 1:
            defaults[k] = vals[0]

    # material types present (for picker label).
    mats: dict[str, None] = {}
    for n in notes:
        mt = n.frontmatter.get("素材类型")
        if isinstance(mt, str) and mt:
            mats.setdefault(mt, None)

    # body shape: majority vote.
    v = sum(_is_variants(n) for n in notes)
    s = sum(_is_spec_table(n) for n in notes)
    shape = "variants" if v >= s and v > 0 else "spec_table" if s > 0 else "unknown"

    return FolderProfile(
        rel_folder=rel_folder,
        frontmatter_keys=keys,
        defaults=defaults,
        body_shape=shape,
        sample_count=len(notes),
        material_types=list(mats.keys()),
    )


def list_writable_folders(index: VaultIndex) -> list[FolderProfile]:
    """Every folder that directly holds ≥1 parsed note, each profiled."""
    rels: dict[str, None] = {}
    for n in index.notes:
        rel = _rel_folder_of(n, index.root)
        if rel:
            rels.setdefault(rel, None)
    return [profile_folder(index, r) for r in sorted(rels)]
