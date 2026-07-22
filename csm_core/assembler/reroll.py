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
from csm_core.angle.filters import effective_filters
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

    # 卡片模式的 pick 必须限定在「该竞品的该小节」/「该主推小节」子池里重抽。
    # 默认路径按**块级** source 重建候选池，对卡片来说那是整个竞品目录 ——
    # 会把别家竞品、别的小节的笔记塞进当前卡位，并且 _build_pick 重建 meta
    # 时会丢掉 section_label/competitor_key，渲染分组当场解体。
    if getattr(block, "sections", None):
        return _reroll_card_pick(
            plan, block_id, pick_index, block, vault_index, rng,
        )

    source = _get_notes_source(block)
    if source is None:
        raise NoCandidatesError(
            f"block '{block_id}' ({type(block).__name__}) does not support reroll"
        )

    current = result.picks[pick_index]
    sibling_note_ids = {
        p.note_id for i, p in enumerate(result.picks) if i != pick_index
    }

    pool = vault_index.query(
        module=source.module, filters=effective_filters(source, plan.angle),
    )

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


def _reroll_card_pick(
    plan: AssemblyPlan, block_id: str, pick_index: int, block,
    vault_index: VaultIndex, rng: random.Random,
) -> AssemblyPlan:
    """卡片 pick 重抽 —— 池子锁死在同一个小节内，meta 原样保留。

    主推卡：小节自己的 module/filter 就是池子。
    竞品卡：Layer1 = 同卡同 H2 段里的其他 ①②③；Layer2 = 该竞品其他也覆盖
    这个小节的卡片笔记。绝不跨竞品、不跨小节。
    """
    from .cards import build_roster, section_body
    from csm_core.template.schema import CompetitorPoolBlock as _Pool
    from csm_core.vault.note_parser import split_variants

    result = plan.get_result(block_id)
    current = result.picks[pick_index]
    sec_index = current.meta.get("section_index")
    if sec_index is None or not (0 <= sec_index < len(block.sections)):
        raise NoCandidatesError(
            f"block '{block_id}' pick {pick_index}: 卡片 pick 缺 section_index"
        )
    spec = block.sections[sec_index]

    if not isinstance(block, _Pool):
        # 主推卡：按小节的目录/筛选重建池，兄弟排除只看同一小节的 picks。
        module = spec.module or (block.source.module if block.source else "")
        # 走 effective_filters —— 采样期是带角度过滤的，重抽不带就会把
        # 角度已排除的素材（比如宝妈向文案换进老年人角度的文章）换进来。
        sec_src = NotesQuerySource(module=module, filter=dict(spec.filter))
        pool = vault_index.query(
            module=module, filters=effective_filters(sec_src, plan.angle),
        )
        siblings = {
            p.note_id for i, p in enumerate(result.picks)
            if i != pick_index and p.meta.get("section_index") == sec_index
        }
        layer1, layer2 = _variant_layers(pool, current, siblings)
        chosen = _choose(layer1, rng) or _choose(layer2, rng)
        if chosen is None:
            raise NoCandidatesError(
                f"block '{block_id}' pick {pick_index}: 小节「{spec.label}」没有其他候选"
            )
        note, vi = chosen
        from .sampler import _rich_variant
        plain = note.variants[vi] if vi < len(note.variants) else note.raw_body
        # 条数对不上就退回普通文本 —— 两种切分理论同构，但真错位时宁可
        # 丢加粗也不能取到别的变体（variant_index 会与索引空间脱钩）。
        text = _rich_variant(note, vi, plain)
        meta = dict(current.meta)
        meta.update({"section_index": sec_index, "section_label": spec.label})
        new_pick = PickedVariant(
            note_id=note.id, variant_index=vi, text=text, meta=meta,
        )
        return _replace_pick(plan, block_id, pick_index, new_pick)

    # 竞品卡
    key = current.meta.get("competitor_key")
    pool = vault_index.query(
        module=block.source.module, filters=block.source.filter,
    )
    roster_notes = [
        n for n in pool
        if _competitor_key_of(n) == key and section_body(n, spec) is not None
    ]
    candidates: list[tuple[str, int, str]] = []      # (note_id, variant, text)
    for n in roster_notes:
        body = section_body(n, spec)
        variants = split_variants(body, keep_bold=True) or [body.strip()]
        for vi, text in enumerate(variants):
            if n.id == current.note_id and vi == current.variant_index:
                continue
            candidates.append((n.id, vi, text))
    if not candidates:
        raise NoCandidatesError(
            f"block '{block_id}' pick {pick_index}: "
            f"竞品「{current.meta.get('title')}」的小节「{spec.label}」没有其他候选"
        )
    note_id, vi, text = rng.choice(candidates)
    new_pick = PickedVariant(
        note_id=note_id, variant_index=vi, text=text, meta=dict(current.meta),
    )
    return _replace_pick(plan, block_id, pick_index, new_pick)


def _competitor_key_of(note: ParsedNote) -> str | None:
    from csm_core.brand_memory.identity import normalize_model_key, note_identity
    ident = note_identity(note.id, note.frontmatter)
    if not ident:
        return None
    brand, raw_model = ident
    return f"{normalize_model_key(brand)}::{normalize_model_key(raw_model)}"


def _variant_layers(
    pool: list[ParsedNote], current: PickedVariant, sibling_note_ids: set[str],
) -> tuple[list[tuple[ParsedNote, int]], list[tuple[ParsedNote, int]]]:
    """(同笔记其他变体, 其他笔记全部变体) —— 与默认路径同款分层。"""
    same_note = next((n for n in pool if n.id == current.note_id), None)
    layer1: list[tuple[ParsedNote, int]] = []
    if same_note is not None:
        for vi in range(len(same_note.variants)):
            if vi != current.variant_index:
                layer1.append((same_note, vi))
    layer2: list[tuple[ParsedNote, int]] = []
    for n in pool:
        if n.id == current.note_id or n.id in sibling_note_ids:
            continue
        if not n.variants:
            layer2.append((n, 0))
            continue
        layer2.extend((n, vi) for vi in range(len(n.variants)))
    return layer1, layer2


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
