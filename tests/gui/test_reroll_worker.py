"""RerollWorker smoke tests — exercise the QThread wrapper."""
from __future__ import annotations
import random
from pathlib import Path
from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.assembler.reroll import NoCandidatesError
from csm_core.template.schema import (
    Template, SEODefaults, NumberedListBlock, NotesQuerySource,
)
from csm_core.vault.scanner import VaultIndex
from csm_core.vault.note_parser import ParsedNote
from csm_gui.workers.reroll import RerollWorker


def _note(nid, variants):
    return ParsedNote(
        path=Path(f"/v/{nid}.md"), id=nid,
        frontmatter={}, variants=variants, raw_body="\n".join(variants),
    )


def _idx(notes):
    idx = VaultIndex(root=Path("/v"))
    idx.notes = list(notes)
    idx.by_id = {n.id: n for n in notes}
    idx.by_module = lambda module: list(notes)  # type: ignore[assignment]
    return idx


def _tpl(block):
    return Template(
        id="t", name="T", product="x", version=1,
        system_prompt_default="", seo_defaults=SEODefaults(),
        blocks=[block],
    )


def _plan(result):
    return AssemblyPlan(keyword="kw", template_id="t", seed=1, results=[result])


def test_reroll_worker_emits_finished_with_new_plan(qtbot):
    notes = [_note("n1", ["A1", "A2"])]
    idx = _idx(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=1)
    plan = _plan(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[PickedVariant(note_id="n1", variant_index=0, text="A1")],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    w = RerollWorker(
        plan=plan, block_id="nl", pick_index=0,
        template=_tpl(block), vault_index=idx, rng=random.Random(1),
    )
    with qtbot.waitSignal(w.finished, timeout=2000) as sig:
        w.start()
    new_plan = sig.args[0]
    assert isinstance(new_plan, AssemblyPlan)
    assert new_plan.get_result("nl").picks[0].variant_index == 1


def test_reroll_worker_emits_failed_on_no_candidates(qtbot):
    notes = [_note("n1", ["only"])]
    idx = _idx(notes)
    block = NumberedListBlock(id="nl", source=NotesQuerySource(module="m"), pick_notes=1)
    plan = _plan(BlockResult(
        block_id="nl", kind="numbered_list",
        picks=[PickedVariant(note_id="n1", variant_index=0, text="only")],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    w = RerollWorker(
        plan=plan, block_id="nl", pick_index=0,
        template=_tpl(block), vault_index=idx, rng=random.Random(1),
    )
    with qtbot.waitSignal(w.failed, timeout=2000) as sig:
        w.start()
    assert "no more candidates" in sig.args[0].lower()
