"""Block-level sampling (dispatch by kind)."""
from __future__ import annotations
import random
from typing import Any
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..vault.note_parser import ParsedNote
from ..template.schema import (
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    NotesQuerySource, BrandFixedSource, BrandPoolSource,
    TestResultsAlignedSource, PickCountSpec, PickNotes,
)
from .plan import BlockResult, PickedVariant


class EmptyPoolError(Exception):
    """Raised when a sample-based block has an empty candidate pool."""


def _resolve_pick_count(
    pick_notes: PickNotes, block_id: str,
    user_config: dict[str, int], rng: random.Random,
) -> int:
    if isinstance(pick_notes, int):
        return pick_notes
    if pick_notes.random_between:
        lo, hi = pick_notes.random_between
        return rng.randint(lo, hi)
    if pick_notes.user_configurable:
        n = user_config.get(block_id, pick_notes.default or 1)
        if pick_notes.range is not None:
            lo, hi = pick_notes.range
            if not (lo <= n <= hi):
                raise ValueError(
                    f"block '{block_id}': pick count {n} out of range [{lo}, {hi}]"
                )
        return n
    return 1


def _pick_variant(note: ParsedNote, rng: random.Random) -> tuple[int, str]:
    if not note.variants:
        return 0, note.raw_body
    idx = rng.randrange(len(note.variants))
    return idx, note.variants[idx]


def _meta_for_note(note: ParsedNote) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("品牌", "型号"):
        if key in note.frontmatter:
            meta["brand" if key == "品牌" else "model"] = note.frontmatter[key]
    return meta


def _sample_notes_source(
    block_id: str, source: NotesQuerySource, constraints: list[str],
    pick_notes: PickNotes, pick_variants_per_note: int,
    index: VaultIndex, rng: random.Random,
    user_config: dict[str, int],
) -> list[PickedVariant]:
    pool = index.query(module=source.module, filters=source.filter)
    if not pool:
        raise EmptyPoolError(f"block '{block_id}': empty pool in module '{source.module}'")
    requested = _resolve_pick_count(pick_notes, block_id, user_config, rng)
    if "unique_notes" in constraints:
        actual = min(requested, len(pool))
        chosen = rng.sample(pool, actual)
    else:
        actual = requested
        chosen = [rng.choice(pool) for _ in range(requested)]
    capped = "unique_notes" in constraints and actual < requested
    picks: list[PickedVariant] = []
    for note in chosen:
        for _ in range(pick_variants_per_note):
            vi, text = _pick_variant(note, rng)
            meta = _meta_for_note(note)
            if capped:
                meta.update({"capped": True, "requested": requested, "available": actual})
            picks.append(PickedVariant(
                note_id=note.id, variant_index=vi, text=text, meta=meta,
            ))
    return picks


def sample_block(
    block, index: VaultIndex, registry: BrandRegistry,
    *, seed: int, user_config: dict[str, int],
    aligned_models: list[str] | None = None,
) -> BlockResult:
    rng = random.Random(f"{seed}-{block.id}")

    if isinstance(block, HeadingBlock):
        return BlockResult(
            block_id=block.id, kind="heading",
            text=block.text,
            meta={"level": block.level, "index": block.index},
        )

    if isinstance(block, LiteralBlock):
        return BlockResult(block_id=block.id, kind="literal", text=block.text)

    if isinstance(block, HeroBrandBlock):
        return BlockResult(
            block_id=block.id, kind="hero_brand", text=block.title,
            meta={
                "number_style": block.number_style,
                "reason_label": block.reason_label,
            },
        )

    if isinstance(block, ParagraphBlock):
        picks = _sample_source_for_block(block, index, registry, rng, user_config, aligned_models)
        return BlockResult(block_id=block.id, kind="paragraph", picks=picks)

    if isinstance(block, NumberedListBlock):
        assert isinstance(block.source, NotesQuerySource), \
            f"numbered_list block '{block.id}' only supports notes_query source"
        picks = _sample_notes_source(
            block.id, block.source, constraints=["unique_notes"],
            pick_notes=block.pick_notes, pick_variants_per_note=1,
            index=index, rng=rng, user_config=user_config,
        )
        return BlockResult(
            block_id=block.id, kind="numbered_list", picks=picks,
            meta={
                "number_style": block.number_style,
                "item_separator": block.item_separator,
            },
        )

    if isinstance(block, CompetitorPoolBlock):
        assert isinstance(block.source, NotesQuerySource), \
            f"competitor_pool block '{block.id}' only supports notes_query source"
        picks = _sample_notes_source(
            block.id, block.source, constraints=["unique_notes"],
            pick_notes=block.pick_notes, pick_variants_per_note=1,
            index=index, rng=rng, user_config=user_config,
        )
        enriched: list[PickedVariant] = []
        for p in picks:
            meta = dict(p.meta)
            raw_title = meta.get("model") or p.note_id
            # Strip the "竞品-" category prefix that comes from folder-based
            # note_id when frontmatter lacks an explicit model field.
            if raw_title.startswith("竞品-"):
                raw_title = raw_title[len("竞品-"):]
            meta["title"] = raw_title
            enriched.append(p.model_copy(update={"meta": meta}))
        return BlockResult(
            block_id=block.id, kind="competitor_pool", picks=enriched,
            meta={"reason_label": block.reason_label},
        )

    raise EmptyPoolError(f"block '{block.id}': unsupported type {type(block).__name__}")


def _sample_source_for_block(
    block: ParagraphBlock, index: VaultIndex, registry: BrandRegistry,
    rng: random.Random, user_config: dict[str, int],
    aligned_models: list[str] | None,
) -> list[PickedVariant]:
    src = block.source
    if isinstance(src, NotesQuerySource):
        return _sample_notes_source(
            block.id, src, block.constraints, block.pick_notes,
            block.pick_variants_per_note, index, rng, user_config,
        )
    if isinstance(src, BrandFixedSource):
        return [PickedVariant(
            note_id=f"{src.model}-fixed", variant_index=0,
            text=f"{src.brand} {src.model}",
            meta={"brand": src.brand, "model": src.model},
        )]
    if isinstance(src, BrandPoolSource):
        candidates = [
            m for m in registry.all_models()
            if registry.brand_of(m) not in src.exclude_brands
        ]
        if not candidates:
            raise EmptyPoolError(f"block '{block.id}': brand pool empty")
        n = _resolve_pick_count(block.pick_notes, block.id, user_config, rng)
        actual = min(n, len(candidates))
        chosen = rng.sample(candidates, actual)
        capped = actual < n
        return [
            PickedVariant(
                note_id=f"{m}-brand", variant_index=0,
                text=f"{registry.brand_of(m)} {m}",
                meta={
                    "brand": registry.brand_of(m), "model": m,
                    **({"capped": True, "requested": n, "available": actual} if capped else {}),
                },
            )
            for m in chosen
        ]
    if isinstance(src, TestResultsAlignedSource):
        if aligned_models is None:
            raise EmptyPoolError(
                f"block '{block.id}': test_results_aligned requires aligned_models"
            )
        picks: list[PickedVariant] = []
        for model in aligned_models:
            matches = index.query(module=src.module, filters={"型号": model})
            note = matches[0] if matches else None
            if note is None:
                picks.append(PickedVariant(
                    note_id=f"__missing__:{model}-测试结果", variant_index=0,
                    text=f"[缺数据：{model} 测试结果]",
                    meta={"model": model, "missing": True},
                ))
            else:
                vi, text = _pick_variant(note, rng)
                picks.append(PickedVariant(
                    note_id=note.id, variant_index=vi, text=text,
                    meta={"model": model, "brand": registry.brand_of(model) or ""},
                ))
        return picks
    raise EmptyPoolError(f"block '{block.id}': unknown source {type(src).__name__}")
