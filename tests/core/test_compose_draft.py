from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.assembler.render import compose_draft


def _mk_plan(slots):
    return AssemblyPlan(keyword="k", template_id="t", seed=0, slots=slots)


def _pick(text):
    return PickedVariant(note_id="n", variant_index=0, text=text)


def test_compose_draft_joins_picks_with_blank_lines_within_slot():
    plan = _mk_plan([SlotAssignment(slot_id="s1", picks=[_pick("a"), _pick("b")])])
    assert compose_draft(plan) == "a\n\nb"


def test_compose_draft_separates_slots_with_blank_lines():
    plan = _mk_plan([
        SlotAssignment(slot_id="s1", picks=[_pick("a")]),
        SlotAssignment(slot_id="s2", picks=[_pick("b")]),
    ])
    assert compose_draft(plan) == "a\n\nb"


def test_compose_draft_skips_empty_slots():
    plan = _mk_plan([
        SlotAssignment(slot_id="s1", picks=[_pick("a")]),
        SlotAssignment(slot_id="s2", picks=[]),
        SlotAssignment(slot_id="s3", picks=[_pick("c")]),
    ])
    assert compose_draft(plan) == "a\n\nc"


def test_compose_draft_empty_plan_returns_empty_string():
    assert compose_draft(_mk_plan([])) == ""
