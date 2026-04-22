"""Two-level random sampling: pick notes → pick variant per note."""
from __future__ import annotations
import random
from typing import Any
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..vault.note_parser import ParsedNote
from ..template.schema import (
    Slot, NotesQuerySource, BrandFixedSource, BrandPoolSource,
    TestResultsAlignedSource, PickCountSpec,
)
from .plan import PickedVariant


class EmptyPoolError(Exception):
    """Raised when a slot's candidate pool is empty."""


def _resolve_pick_count(
    pick_notes: int | PickCountSpec,
    slot_id: str,
    user_config: dict[str, int],
    rng: random.Random,
) -> int:
    if isinstance(pick_notes, int):
        return pick_notes
    if pick_notes.random_between:
        lo, hi = pick_notes.random_between
        return rng.randint(lo, hi)
    if pick_notes.user_configurable:
        n = user_config.get(slot_id, pick_notes.default or 1)
        if pick_notes.range is not None:
            lo, hi = pick_notes.range
            if not (lo <= n <= hi):
                raise ValueError(
                    f"slot '{slot_id}': pick count {n} out of range [{lo}, {hi}]"
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


def sample_slot(
    slot: Slot,
    index: VaultIndex,
    registry: BrandRegistry,
    seed: int,
    user_config: dict[str, int],
    aligned_models: list[str] | None = None,
) -> list[PickedVariant]:
    """Sample a single slot. `aligned_models` is for test_results_aligned source."""
    rng = random.Random(f"{seed}-{slot.id}")
    src = slot.source

    if isinstance(src, NotesQuerySource):
        pool = index.query(module=src.module, filters=src.filter)
        if not pool:
            raise EmptyPoolError(f"slot '{slot.id}': empty pool in module '{src.module}'")
        requested = _resolve_pick_count(slot.pick_notes, slot.id, user_config, rng)
        if "unique_notes" in slot.constraints:
            actual = min(requested, len(pool))
            chosen = rng.sample(pool, actual)
        else:
            actual = requested
            chosen = [rng.choice(pool) for _ in range(requested)]
        capped = "unique_notes" in slot.constraints and actual < requested
        picks: list[PickedVariant] = []
        for note in chosen:
            for _ in range(slot.pick_variants_per_note):
                vi, text = _pick_variant(note, rng)
                meta = _meta_for_note(note)
                if capped:
                    meta.update({"capped": True, "requested": requested, "available": actual})
                picks.append(PickedVariant(
                    note_id=note.id, variant_index=vi, text=text, meta=meta,
                ))
        return picks

    if isinstance(src, BrandFixedSource):
        return [PickedVariant(
            note_id=f"{src.model}-fixed",
            variant_index=0,
            text=f"{src.brand} {src.model}",
            meta={"brand": src.brand, "model": src.model},
        )]

    if isinstance(src, BrandPoolSource):
        candidates = [
            m for m in registry.all_models()
            if registry.brand_of(m) not in src.exclude_brands
        ]
        if not candidates:
            raise EmptyPoolError(f"slot '{slot.id}': brand pool empty")
        n = _resolve_pick_count(slot.pick_notes, slot.id, user_config, rng)
        actual = min(n, len(candidates))
        chosen = rng.sample(candidates, actual)
        capped = actual < n
        return [
            PickedVariant(
                note_id=f"{m}-brand",
                variant_index=0,
                text=f"{registry.brand_of(m)} {m}",
                meta={
                    "brand": registry.brand_of(m),
                    "model": m,
                    **({"capped": True, "requested": n, "available": actual} if capped else {}),
                },
            )
            for m in chosen
        ]

    if isinstance(src, TestResultsAlignedSource):
        if aligned_models is None:
            raise EmptyPoolError(
                f"slot '{slot.id}': test_results_aligned requires aligned_models"
            )
        picks = []
        for model in aligned_models:
            matches = index.query(module=src.module, filters={"型号": model})
            note = matches[0] if matches else None
            if not note:
                picks.append(PickedVariant(
                    note_id=f"__missing__:{model}-测试结果",
                    variant_index=0,
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

    raise EmptyPoolError(f"slot '{slot.id}': unknown source type {type(src)}")
