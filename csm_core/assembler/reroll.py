"""Per-pick reroll on AssemblyPlan.

Given an existing plan plus a target (block_id, pick_index), produce a new
plan with the target pick replaced by a fresh sample. Strategy:
  1. Prefer other variants of the same note (minimal perturbation).
  2. Fall back to different notes in the same source pool.
  3. Raise NoCandidatesError when neither layer has anything left.

Sibling picks' note_ids are always excluded so unique-notes semantics hold.
"""
from __future__ import annotations
import random
from pathlib import Path
from typing import Iterable
from ..template.schema import (
    Template, ParagraphBlock, NumberedListBlock, CompetitorPoolBlock,
    NotesQuerySource,
)
from ..vault.scanner import VaultIndex
from ..vault.note_parser import ParsedNote
from .plan import AssemblyPlan, BlockResult, PickedVariant


class NoCandidatesError(Exception):
    """Raised when a reroll has no eligible candidate to swap in."""


def reroll_pick(
    plan: AssemblyPlan,
    block_id: str,
    pick_index: int,
    template: Template,
    vault_index: VaultIndex,
    *,
    rng: random.Random | None = None,
) -> AssemblyPlan:
    rng = rng or random.Random()

    result = plan.get_result(block_id)
    if result is None:
        raise NoCandidatesError(f"block '{block_id}' not found in plan")
    if not (0 <= pick_index < len(result.picks)):
        raise NoCandidatesError(
            f"block '{block_id}' has {len(result.picks)} picks; index {pick_index} out of range"
        )

    block = _find_block(template, block_id)
    if block is None:
        raise NoCandidatesError(f"block '{block_id}' not found in template")

    source = _get_notes_source(block)
    if source is None:
        raise NoCandidatesError(
            f"block '{block_id}' ({type(block).__name__}) does not support reroll"
        )

    current = result.picks[pick_index]
    sibling_note_ids = {
        p.note_id for i, p in enumerate(result.picks) if i != pick_index
    }

    pool = vault_index.query(module=source.module, filters=source.filter)

    # Layer 1: other variants of the same note.
    same_note = next((n for n in pool if n.id == current.note_id), None)
    layer1: list[tuple[ParsedNote, int]] = []
    if same_note is not None:
        for vi in range(len(same_note.variants)):
            if vi == current.variant_index:
                continue
            layer1.append((same_note, vi))

    # Layer 2: other notes entirely (exclude current + siblings).
    layer2: list[tuple[ParsedNote, int]] = []
    for n in pool:
        if n.id == current.note_id:
            continue
        if n.id in sibling_note_ids:
            continue
        if not n.variants:
            layer2.append((n, 0))
            continue
        for vi in range(len(n.variants)):
            layer2.append((n, vi))

    chosen = _choose(layer1, rng) or _choose(layer2, rng)
    if chosen is None:
        raise NoCandidatesError(
            f"block '{block_id}' pick {pick_index}: no more candidates"
        )

    note, vi = chosen
    new_pick = _build_pick(note, vi, result, template, block)
    return _replace_pick(plan, block_id, pick_index, new_pick)


def _find_block(template: Template, block_id: str):
    """Recursive lookup matching AssemblyPlan.get_result."""
    def walk(items):
        for b in items:
            if b.id == block_id:
                return b
            if isinstance(b, ParagraphBlock):
                found = walk(b.children)
                if found is not None:
                    return found
        return None
    return walk(template.blocks)


def _get_notes_source(block) -> NotesQuerySource | None:
    if isinstance(block, (NumberedListBlock, CompetitorPoolBlock)):
        src = block.source
        return src if isinstance(src, NotesQuerySource) else None
    if isinstance(block, ParagraphBlock):
        src = block.source
        return src if isinstance(src, NotesQuerySource) else None
    return None


def _choose(
    candidates: list[tuple[ParsedNote, int]],
    rng: random.Random,
) -> tuple[ParsedNote, int] | None:
    if not candidates:
        return None
    return rng.choice(candidates)


def _build_pick(
    note: ParsedNote, variant_index: int,
    result: BlockResult, template: Template, block,
) -> PickedVariant:
    text = note.variants[variant_index] if note.variants else note.raw_body
    meta: dict = {}
    for key, attr in (("品牌", "brand"), ("型号", "model")):
        if key in note.frontmatter:
            meta[attr] = note.frontmatter[key]
    # competitor_pool enriches meta['title']: mirror sampler.py behaviour,
    # including the 竞品-prefix strip so rerolled competitors match fresh
    # samples.
    if isinstance(block, CompetitorPoolBlock):
        from .sampler import _clean_competitor_title
        meta["title"] = _clean_competitor_title(meta.get("model") or note.id)
    return PickedVariant(
        note_id=note.id, variant_index=variant_index, text=text, meta=meta,
    )


def _replace_pick(
    plan: AssemblyPlan, block_id: str, pick_index: int, new_pick: PickedVariant,
) -> AssemblyPlan:
    """Return a copy of ``plan`` with the target pick replaced."""
    def walk(items: Iterable[BlockResult]) -> list[BlockResult]:
        out: list[BlockResult] = []
        for r in items:
            if r.block_id == block_id:
                new_picks = list(r.picks)
                new_picks[pick_index] = new_pick
                out.append(r.model_copy(update={"picks": new_picks}))
            elif r.children:
                out.append(r.model_copy(update={"children": walk(r.children)}))
            else:
                out.append(r)
        return out
    return plan.model_copy(update={"results": walk(plan.results)})
