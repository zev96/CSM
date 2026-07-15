"""Infer what shape to write into a vault folder from its existing notes.

The vault is the source of truth (CLAUDE.md has drifted), so the intake form
mirrors a target folder's existing notes rather than a hardcoded taxonomy.

2026-07 起 vault 是多产品线布局(模块/<产品线>/子类),树枚举走文件系统全目录
(含中间层与空目录);空目录借"同叶名、同深度、恰差一段"的兄弟目录模板,产品
默认值随差异段替换。
"""
from __future__ import annotations

import os
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
    template_from: str | None = None   # 空目录借模板的来源目录(rel);非借用 None


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


def _all_dirs(root) -> list[str]:
    """vault 根下全部非隐藏目录(rel, '/'-joined),点开头目录整棵剪枝。"""
    out: list[str] = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for d in dirnames:
            rel = os.path.relpath(os.path.join(dirpath, d), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _borrow_profile(rel: str, profiled: dict[str, FolderProfile]) -> FolderProfile:
    """空目录模板:借"同叶名、同深度、恰差一段"的兄弟;取样本最多者。

    产品默认值仅当兄弟的差异段==其 产品 默认值时才替换(即差异段确为产品线);
    同线跨模块借用时差异段是模块名,不动 产品。无兄弟 → 通用三件套。
    """
    segs = rel.split("/")
    best: FolderProfile | None = None
    best_target_seg = ""
    best_cand_seg = ""
    for cand_rel, prof in profiled.items():
        csegs = cand_rel.split("/")
        if len(csegs) != len(segs) or csegs[-1] != segs[-1]:
            continue
        diffs = [i for i in range(len(segs)) if csegs[i] != segs[i]]
        if len(diffs) != 1:
            continue
        if best is None or prof.sample_count > best.sample_count:
            best = prof
            best_target_seg = segs[diffs[0]]
            best_cand_seg = csegs[diffs[0]]
    if best is None:
        return FolderProfile(
            rel_folder=rel, frontmatter_keys=list(_LEAD_KEYS),
            body_shape="variants")
    defaults = dict(best.defaults)
    if defaults.get("产品") == best_cand_seg:
        defaults["产品"] = best_target_seg
    return FolderProfile(
        rel_folder=rel,
        frontmatter_keys=list(best.frontmatter_keys),
        defaults=defaults,
        body_shape=best.body_shape,
        sample_count=0,
        material_types=list(best.material_types),
        template_from=best.rel_folder,
    )


def list_writable_folders(index: VaultIndex) -> list[FolderProfile]:
    """vault 全部非隐藏目录:有直属笔记的照常 profile,空目录借兄弟模板。"""
    with_notes: dict[str, None] = {}
    for n in index.notes:
        rel = _rel_folder_of(n, index.root)
        if rel:
            with_notes.setdefault(rel, None)
    profiled = {r: profile_folder(index, r) for r in with_notes}
    out: list[FolderProfile] = []
    for rel in _all_dirs(index.root):
        out.append(profiled.get(rel) or _borrow_profile(rel, profiled))
    return out
