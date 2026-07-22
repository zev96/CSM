"""Block-level sampling (dispatch by kind)."""
from __future__ import annotations
import random
import re
from typing import Any

# ``竞品`` is the Chinese category word (≈ "competitor"). Notes are often
# filed under a folder or named with a ``竞品`` prefix followed by some
# separator — hyphen, en/em dash, slash, whitespace, or nothing — before
# the real brand/model. Strip it so the rendered title is clean.
_COMPETITOR_PREFIX_RE = re.compile(r"^竞品[\s\-\u2010-\u2015\uFF0D\u3000/／_:：]*")


def _clean_competitor_title(raw: str) -> str:
    """Strip the ``竞品`` category prefix from a competitor title.

    Handles various separator styles: ASCII hyphen (``竞品-戴森``), full-width
    hyphen (``竞品－戴森``), en/em dash (``竞品–戴森``), slash (``竞品/戴森``),
    whitespace (``竞品 戴森``), or no separator (``竞品戴森``).
    """
    return _COMPETITOR_PREFIX_RE.sub("", raw).strip()
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..vault.note_parser import ParsedNote, split_variants
from ..template.schema import (
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    NotesQuerySource, BrandFixedSource, BrandPoolSource,
    TestResultsAlignedSource, PickCountSpec, PickNotes,
)
from csm_core.angle.model import Angle
from csm_core.angle.filters import effective_filters
from .cards import (
    build_roster, pick_section_variants, sample_roster, set_tier,
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


def _rich_variant(note: ParsedNote, variant_index: int, fallback: str) -> str:
    """同一个变体的「保留加粗」版本。

    重跑一遍 keep_bold 切分（切分逻辑完全相同，所以序号一一对应），只在
    条数对得上时才替换 —— 对不上说明有意外差异，宁可退回普通文本也不能
    错位取到别的变体。
    """
    if not note.variants:
        return note.raw_body or fallback
    rich = split_variants(note.raw_body, keep_bold=True)
    if len(rich) == len(note.variants) and 0 <= variant_index < len(rich):
        return rich[variant_index]
    return fallback


def _sample_notes_source(
    block_id: str, source: NotesQuerySource, constraints: list[str],
    pick_notes: PickNotes, pick_variants_per_note: int,
    index: VaultIndex, rng: random.Random,
    user_config: dict[str, int],
    angle: "Angle | None" = None,
    note_weights: dict[str, float] | None = None,
    keep_bold: bool = False,
) -> list[PickedVariant]:
    eff = effective_filters(source, angle)
    pool = index.query(module=source.module, filters=eff)
    if not pool and eff != (source.filter or {}):
        # 角度过滤把池清空了 → 回退不带角度过滤（别让角度把文章搞空）
        import logging
        logging.getLogger(__name__).info(
            "block '%s': 角度过滤后空池，回退不过滤", block_id,
        )
        pool = index.query(module=source.module, filters=source.filter)
    if not pool:
        raise EmptyPoolError(f"block '{block_id}': empty pool in module '{source.module}'")
    requested = _resolve_pick_count(pick_notes, block_id, user_config, rng)
    if "unique_notes" in constraints:
        actual = min(requested, len(pool))
        chosen = rng.sample(pool, actual)      # 唯一分支 v1 不加权（无放回加权复杂，留边界）
    else:
        actual = requested
        if not note_weights:
            # 零回归铁律：无权重（None 或 {}）逐字节走今天的 rng.choice 循环，
            # RNG 消耗序列不变 —— 绝不能统一换成 rng.choices（会变序列、破坏同种子复现）。
            chosen = [rng.choice(pool) for _ in range(requested)]
        else:
            weights = [note_weights.get(n.id, 1.0) for n in pool]
            chosen = rng.choices(pool, weights=weights, k=requested)
    capped = "unique_notes" in constraints and actual < requested
    picks: list[PickedVariant] = []
    for note in chosen:
        for _ in range(pick_variants_per_note):
            vi, text = _pick_variant(note, rng)
            if keep_bold:
                text = _rich_variant(note, vi, text)
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
    angle: "Angle | None" = None,
    note_weights: dict[str, float] | None = None,
    exclude_competitor_keys: set[str] | None = None,
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
        if block.sections:
            return _sample_hero_card(
                block, index, rng, user_config, angle, note_weights,
            )
        return BlockResult(
            block_id=block.id, kind="hero_brand", text=block.title,
            meta={
                "number_style": block.number_style,
                "reason_label": block.reason_label,
            },
        )

    if isinstance(block, ParagraphBlock):
        picks = _sample_source_for_block(
            block, index, registry, rng, user_config, aligned_models, angle,
            note_weights=note_weights,
        )
        return BlockResult(block_id=block.id, kind="paragraph", picks=picks)

    if isinstance(block, NumberedListBlock):
        assert isinstance(block.source, NotesQuerySource), \
            f"numbered_list block '{block.id}' only supports notes_query source"
        picks = _sample_notes_source(
            block.id, block.source, constraints=block.constraints,
            pick_notes=block.pick_notes,
            pick_variants_per_note=block.pick_variants_per_note,
            index=index, rng=rng, user_config=user_config, angle=angle,
            note_weights=note_weights,
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
        if block.sections:
            return sample_competitor_cards(
                block, index, rng, user_config,
                exclude_keys=exclude_competitor_keys or set(),
            )
        picks = _sample_notes_source(
            block.id, block.source, constraints=block.constraints,
            pick_notes=block.pick_notes,
            pick_variants_per_note=block.pick_variants_per_note,
            index=index, rng=rng, user_config=user_config, angle=angle,
            note_weights=note_weights,
        )
        enriched: list[PickedVariant] = []
        for p in picks:
            meta = dict(p.meta)
            raw_title = meta.get("model") or p.note_id
            meta["title"] = _clean_competitor_title(raw_title)
            enriched.append(p.model_copy(update={"meta": meta}))
        return BlockResult(
            block_id=block.id, kind="competitor_pool", picks=enriched,
            meta={"reason_label": block.reason_label},
        )

    raise EmptyPoolError(f"block '{block.id}': unsupported type {type(block).__name__}")


def _sample_hero_card(
    block: HeroBrandBlock, index: VaultIndex, rng: random.Random,
    user_config: dict[str, int], angle: "Angle | None",
    note_weights: dict[str, float] | None,
) -> BlockResult:
    """主推卡：逐小节从素材池抽内容，打平成 picks。

    与 legacy hero 的区别是它自包含 —— 不吞并后续段落块、不输出
    ``推荐理由：``，标题行由 heading_template 决定。每个小节独立配目录和
    筛选，所以「品牌实力」和「核心参数」可以各自随机组合。
    """
    picks: list[PickedVariant] = []
    for i, sec in enumerate(block.sections):
        module = sec.module or (block.source.module if block.source else "")
        src = NotesQuerySource(module=module, filter=dict(sec.filter))
        sec_picks = _sample_notes_source(
            f"{block.id}#{i + 1}·{sec.label or '正文'}", src,
            constraints=["unique_notes"],
            pick_notes=sec.pick_notes,
            pick_variants_per_note=sec.pick_variants_per_note,
            index=index, rng=rng, user_config=user_config, angle=angle,
            note_weights=note_weights,
            keep_bold=True,
        )
        for p in sec_picks:
            meta = dict(p.meta)
            meta.update({"section_index": i, "section_label": sec.label})
            picks.append(p.model_copy(update={"meta": meta}))
    return BlockResult(
        block_id=block.id, kind="hero_brand", text=block.title, picks=picks,
        meta={
            "card": True,
            "number_style": block.number_style,
            "heading_template": block.heading_template,
            "tier": block.tier,
            "label_layout": block.label_layout,
            "section_labels": [s.label for s in block.sections],
        },
    )


def sample_competitor_cards(
    block: CompetitorPoolBlock, index: VaultIndex, rng: random.Random,
    user_config: dict[str, int], *, exclude_keys: set[str],
) -> BlockResult:
    """竞品卡池：建名册 → 覆盖度预检 → 抽 N 个竞品 → 逐小节抽内容。

    卡片模式不吃角度过滤（legacy 路径会按人群角度追加 filter 并在空池时
    回退）—— 竞品目录不带人群标记，套角度只会把名册打空。
    """
    pool = index.query(module=block.source.module, filters=block.source.filter)
    roster, roster_warnings = build_roster(pool, block.sections)
    for card in roster:
        set_tier(card, block.tier_key)

    requested = _resolve_pick_count(block.pick_notes, block.id, user_config, rng)
    fixed = isinstance(block.pick_notes, int)
    chosen, cap_note = sample_roster(
        roster, requested, rng,
        exclude_keys=exclude_keys, block_id=block.id, fixed_count=fixed,
        roster_warnings=roster_warnings,
    )

    picks: list[PickedVariant] = []
    for card in chosen:
        for i, spec in enumerate(block.sections):
            body = card.sections.get(spec.label)
            if body is None:
                continue          # required 小节缺失的竞品已在建册时剔除
            for vi, text in pick_section_variants(body, spec.pick_variants, rng):
                picks.append(PickedVariant(
                    note_id=card.note.id, variant_index=vi, text=text,
                    meta={
                        "brand": card.brand, "model": card.model,
                        "title": card.title, "tier": card.tier,
                        "competitor_key": card.key,
                        "section_index": i, "section_label": spec.label,
                    },
                ))
    result = BlockResult(
        block_id=block.id, kind="competitor_pool", picks=picks,
        meta={
            "card": True,
            "heading_template": block.heading_template,
            "label_layout": block.label_layout,
            "card_separator": block.card_separator,
            "competitor_keys": [c.key for c in chosen],
            "roster_warnings": roster_warnings,
        },
    )
    if cap_note:
        result.note = cap_note
    return result


def _sample_source_for_block(
    block: ParagraphBlock, index: VaultIndex, registry: BrandRegistry,
    rng: random.Random, user_config: dict[str, int],
    aligned_models: list[str] | None,
    angle: "Angle | None" = None,
    note_weights: dict[str, float] | None = None,
) -> list[PickedVariant]:
    src = block.source
    if isinstance(src, NotesQuerySource):
        return _sample_notes_source(
            block.id, src, block.constraints, block.pick_notes,
            block.pick_variants_per_note, index, rng, user_config,
            angle=angle, note_weights=note_weights,
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
