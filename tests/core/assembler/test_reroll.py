"""Tests for per-pick reroll on AssemblyPlan."""
from __future__ import annotations
import random
from pathlib import Path
import pytest
from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.assembler.reroll import reroll_pick, NoCandidatesError
from csm_core.template.schema import (
    Template, SEODefaults, ParagraphBlock, NumberedListBlock,
    CompetitorPoolBlock, NotesQuerySource,
)
from csm_core.vault.note_parser import ParsedNote
from csm_core.vault.scanner import VaultIndex


def _note(nid: str, variants: list[str], frontmatter: dict | None = None) -> ParsedNote:
    return ParsedNote(
        path=Path(f"/vault/{nid}.md"),
        id=nid,
        frontmatter=frontmatter or {"素材类型": "引言痛点"},
        variants=variants,
        raw_body="\n".join(variants),
    )


def _index_from(notes: list[ParsedNote]) -> VaultIndex:
    idx = VaultIndex(root=Path("/vault"))
    idx.notes = list(notes)
    idx.by_id = {n.id: n for n in notes}
    idx.by_module = lambda module: list(notes)  # type: ignore[assignment]
    return idx


def _tpl_with(block) -> Template:
    return Template(
        id="t", name="T", product="吸尘器", version=1,
        system_prompt_default="", seo_defaults=SEODefaults(),
        blocks=[block],
    )


def _plan_with(result: BlockResult) -> AssemblyPlan:
    return AssemblyPlan(keyword="kw", template_id="t", seed=1, results=[result])


def test_reroll_prefers_sibling_variant():
    """When the current pick's note has untried variants, swap variant not note."""
    notes = [_note("n1", ["A1", "A2", "A3"]), _note("n2", ["B1"])]
    idx = _index_from(notes)
    block = NumberedListBlock(
        id="nl", source=NotesQuerySource(module="m"), pick_notes=1,
    )
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[PickedVariant(note_id="n1", variant_index=0, text="A1")],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    new_plan = reroll_pick(plan, "nl", 0, tpl, idx, rng=random.Random(7))
    new_pick = new_plan.get_result("nl").picks[0]
    assert new_pick.note_id == "n1"
    assert new_pick.variant_index in (1, 2)
    assert new_pick.text in ("A2", "A3")


def test_reroll_falls_back_to_different_note():
    """With only one variant on the current note, reroll must change note."""
    notes = [_note("n1", ["only"]), _note("n2", ["B1"]), _note("n3", ["C1"])]
    idx = _index_from(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=1)
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[PickedVariant(note_id="n1", variant_index=0, text="only")],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    new_plan = reroll_pick(plan, "nl", 0, tpl, idx, rng=random.Random(3))
    assert new_plan.get_result("nl").picks[0].note_id in {"n2", "n3"}


def test_reroll_numbered_list_keeps_other_picks():
    notes = [_note("n1", ["A"]), _note("n2", ["B"]), _note("n3", ["C1", "C2"])]
    idx = _index_from(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=2)
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[
            PickedVariant(note_id="n1", variant_index=0, text="A"),
            PickedVariant(note_id="n2", variant_index=0, text="B"),
        ],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    new_plan = reroll_pick(plan, "nl", 0, tpl, idx, rng=random.Random(1))
    picks = new_plan.get_result("nl").picks
    assert picks[1].note_id == "n2" and picks[1].text == "B"
    assert picks[0].note_id == "n3"


def test_reroll_respects_unique_notes_across_siblings():
    notes = [_note("n1", ["A"]), _note("n2", ["B"]), _note("n3", ["C"])]
    idx = _index_from(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=2)
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[
            PickedVariant(note_id="n1", variant_index=0, text="A"),
            PickedVariant(note_id="n2", variant_index=0, text="B"),
        ],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    new_plan = reroll_pick(plan, "nl", 0, tpl, idx, rng=random.Random(4))
    assert new_plan.get_result("nl").picks[0].note_id == "n3"


def test_reroll_competitor_pool_sets_title_meta():
    notes = [
        _note("n1", ["r1"], frontmatter={"型号": "X1"}),
        _note("n2", ["r2"], frontmatter={"型号": "X2"}),
        _note("n3", ["r3"], frontmatter={"型号": "X3"}),
    ]
    idx = _index_from(notes)
    block = CompetitorPoolBlock(id="cp", source=NotesQuerySource(module="m"), pick_notes=2)
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="cp", kind="competitor_pool",
        picks=[
            PickedVariant(note_id="n1", variant_index=0, text="r1",
                          meta={"model": "X1", "title": "X1"}),
            PickedVariant(note_id="n2", variant_index=0, text="r2",
                          meta={"model": "X2", "title": "X2"}),
        ],
        meta={"reason_label": "推荐理由："},
    ))
    new_plan = reroll_pick(plan, "cp", 0, tpl, idx, rng=random.Random(2))
    picks = new_plan.get_result("cp").picks
    assert picks[0].note_id == "n3"
    assert picks[0].meta["title"] == "X3"
    assert picks[1].note_id == "n2"


def test_reroll_competitor_pool_strips_jingpin_prefix():
    """Reroll of a competitor pick must strip the 竞品- prefix from title,
    mirroring the initial sample. Otherwise a rerolled pick would reintroduce
    the category prefix that fresh samples don't have."""
    notes = [
        _note("n1", ["r1"], frontmatter={"型号": "X1"}),
        _note("n2", ["r2"], frontmatter={"型号": "X2"}),
        _note("竞品-戴森V8", ["r3"], frontmatter={"产品": "吸尘器"}),
    ]
    idx = _index_from(notes)
    block = CompetitorPoolBlock(
        id="cp", source=NotesQuerySource(module="m"), pick_notes=2,
    )
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="cp", kind="competitor_pool",
        picks=[
            PickedVariant(note_id="n1", variant_index=0, text="r1",
                          meta={"model": "X1", "title": "X1"}),
            PickedVariant(note_id="n2", variant_index=0, text="r2",
                          meta={"model": "X2", "title": "X2"}),
        ],
        meta={"reason_label": "推荐理由："},
    ))
    new_plan = reroll_pick(plan, "cp", 0, tpl, idx, rng=random.Random(2))
    new_pick = new_plan.get_result("cp").picks[0]
    assert new_pick.note_id == "竞品-戴森V8"
    assert new_pick.meta["title"] == "戴森V8"  # prefix stripped


def test_reroll_paragraph_leaves_children_untouched():
    notes_parent = [_note("p1", ["P1"]), _note("p2", ["P2"])]
    idx = _index_from(notes_parent)
    parent = ParagraphBlock(
        id="par", source=NotesQuerySource(module="m"),
        children=[ParagraphBlock(id="child", source=NotesQuerySource(module="m"))],
    )
    tpl = _tpl_with(parent)
    plan = _plan_with(BlockResult(
        block_id="par", kind="paragraph",
        picks=[PickedVariant(note_id="p1", variant_index=0, text="P1")],
        children=[BlockResult(
            block_id="child", kind="paragraph",
            picks=[PickedVariant(note_id="c1", variant_index=0, text="C1")],
        )],
    ))
    new_plan = reroll_pick(plan, "par", 0, tpl, idx, rng=random.Random(1))
    parent_res = new_plan.get_result("par")
    assert parent_res.picks[0].note_id == "p2"
    assert len(parent_res.children) == 1
    child_res = parent_res.children[0]
    assert child_res.picks[0].note_id == "c1"
    assert child_res.picks[0].text == "C1"


def test_reroll_raises_when_pool_exhausted():
    notes = [_note("n1", ["only"])]
    idx = _index_from(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=1)
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[PickedVariant(note_id="n1", variant_index=0, text="only")],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    with pytest.raises(NoCandidatesError):
        reroll_pick(plan, "nl", 0, tpl, idx, rng=random.Random(1))


def test_reroll_raises_on_unknown_block():
    notes = [_note("n1", ["A"])]
    idx = _index_from(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=1)
    tpl = _tpl_with(block)
    plan = _plan_with(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[PickedVariant(note_id="n1", variant_index=0, text="A")],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    with pytest.raises(NoCandidatesError):
        reroll_pick(plan, "missing", 0, tpl, idx, rng=random.Random(1))
