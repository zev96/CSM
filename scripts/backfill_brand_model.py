"""One-shot vault enhancement: backfill 品牌/型号/适用型号 frontmatter from filenames.

Usage:
    # dry-run (default): print would-change list + 无法解析清单; writes NOTHING
    python -m scripts.backfill_brand_model "<vault_root>"
    # apply: copy each modified file into <backup_dir> first, then edit in place
    python -m scripts.backfill_brand_model "<vault_root>" --apply --backup-dir "<dir>"

Folder routing (additive only — never overwrites an existing key, idempotent):
    产品参数/*.md            -> add 品牌(canonical) + 型号(full stem, e.g. CEWEYDS18)
    品牌产品测试结果/*.md     -> add 品牌(canonical) + 型号(full stem) [既有 型号 保留]
    品牌背书/*.md            -> add 品牌(canonical) only (brand-level)
    核心技术/次要技术/*.md    -> add 品牌(canonical) + 适用型号 [该品牌 产品参数 全名型号列表]

品牌 is folded to canonical (米家->小米, 希喂->CEWEY) via brand_memory.identity.
型号 keeps the full-stem convention (incl. brand prefix) so it stays consistent with
build_brand_registry + the assembler 型号-join. Notes whose brand/model can't be
derived go to the 无法解析清单 (never guessed). See the plan's 关键设计决定 section.
"""
from __future__ import annotations
import argparse
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from csm_core.brand_memory.identity import (
    BRAND_ALIASES, canonical_brand, parse_brand_model,
)

logger = logging.getLogger(__name__)

_SUFFIXES = ("-产品参数", "-测试结果")
_PARAM_DIR = "产品参数"
_TEST_DIR = "品牌产品测试结果"
_ENDORSE_DIR = "品牌背书"
_SCRIPT_DIRS = ("核心技术", "次要技术")
_WRITING_SUFFIX = "推荐内容"  # 文件夹 <品牌别名>推荐内容


@dataclass
class NotePlan:
    """What SHOULD be present on a note (derived purely from its path)."""
    keys: dict
    unparseable: str | None = None


def _full_stem_model(stem: str) -> str:
    """Stem minus a trailing -产品参数 / -测试结果 (brand prefix kept)."""
    for suf in _SUFFIXES:
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def _brand_from_writing_folder(
    rel_parts: tuple[str, ...], aliases: dict[str, list[str]],
) -> str | None:
    """Canonical brand from a '<alias>推荐内容' ancestor folder, else None.

    '竞品推荐内容' folds to '竞品' which is not a known brand -> None (correctly
    excluded; 竞品推荐内容 is not a backfill target anyway).
    """
    for part in rel_parts:
        if part.endswith(_WRITING_SUFFIX):
            canon = canonical_brand(part[: -len(_WRITING_SUFFIX)], aliases)
            if canon in aliases:
                return canon
    return None


def build_brand_models(
    vault_root: Path, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> dict[str, list[str]]:
    """canonical brand -> [full-stem models], from 产品参数 filenames."""
    out: dict[str, list[str]] = {}
    for md in sorted(Path(vault_root).rglob(f"{_PARAM_DIR}/*.md")):
        parsed = parse_brand_model(md.stem, aliases)
        if not parsed:
            continue
        brand = canonical_brand(parsed[0], aliases)
        model = _full_stem_model(md.stem)
        out.setdefault(brand, [])
        if model not in out[brand]:
            out[brand].append(model)
    return out


def derive_note_plan(
    rel_parts: tuple[str, ...], stem: str,
    brand_models: dict[str, list[str]], aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> NotePlan | None:
    """Target keys for a note, or None if it's not a backfill target."""
    parts = set(rel_parts)
    if _PARAM_DIR in parts or _TEST_DIR in parts:
        kind = "产品参数" if _PARAM_DIR in parts else "测试结果"
        parsed = parse_brand_model(stem, aliases)
        if not parsed:
            return NotePlan(keys={}, unparseable=f"{stem}: {kind} 文件名无法解析品牌前缀")
        brand = canonical_brand(parsed[0], aliases)
        return NotePlan(keys={"品牌": brand, "型号": _full_stem_model(stem)})
    if _ENDORSE_DIR in parts:
        brand = _brand_from_writing_folder(rel_parts, aliases)
        if not brand:
            return NotePlan(keys={}, unparseable=f"{stem}: 品牌背书 无法从文件夹解析品牌")
        return NotePlan(keys={"品牌": brand})
    if parts & set(_SCRIPT_DIRS):
        brand = _brand_from_writing_folder(rel_parts, aliases)
        if not brand:
            return NotePlan(keys={}, unparseable=f"{stem}: 技术话术 无法从文件夹解析品牌")
        keys: dict = {"品牌": brand}
        models = brand_models.get(brand, [])
        if models:
            keys["适用型号"] = list(models)
        return NotePlan(keys=keys)
    return None


def _render_kv(key: str, value) -> str:
    if isinstance(value, list):
        return f"{key}: [{', '.join(str(v) for v in value)}]"
    return f"{key}: {value}"


def insert_frontmatter_keys(text: str, keys: dict) -> str:
    """Insert 'k: v' lines just before the closing '---' of the frontmatter block.

    Preserves the file's newline style and everything else verbatim. ``text``
    must start with a '---' frontmatter block (BOM already stripped by caller).
    Returns ``text`` unchanged when ``keys`` is empty. We do text-level insertion
    (NOT frontmatter.dumps) on purpose: python-frontmatter would reorder/reflow
    the team's existing YAML and blow up the diff on a shared vault.
    """
    if not keys:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    if not lines or lines[0].strip() != "---":
        raise ValueError("no frontmatter block at start of note")
    close_idx = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"), None,
    )
    if close_idx is None:
        raise ValueError("unterminated frontmatter block")
    new_lines = [_render_kv(k, v) for k, v in keys.items()]
    return nl.join(lines[:close_idx] + new_lines + lines[close_idx:])
