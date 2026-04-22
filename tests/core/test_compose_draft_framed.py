from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.assembler.render import compose_draft_framed
from csm_core.framework.schema import Framework, HeadingBlock, ParagraphBlock


def test_compose_draft_framed_delegates_to_renderer():
    plan = AssemblyPlan(keyword="K", template_id="t", seed=0, slots=[
        SlotAssignment(slot_id="s1", picks=[
            PickedVariant(note_id="n", variant_index=0, text="body"),
        ]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"], blocks=[
        HeadingBlock(kind="heading", level=2, index="一", text="{keyword}怎么选"),
        ParagraphBlock(kind="paragraph", slot="s1"),
    ])
    assert compose_draft_framed(plan, fw, {"keyword": "吸尘器"}) \
        == "## 一、吸尘器怎么选\n\nbody"


def test_compose_draft_framed_accepts_trace():
    from csm_core.framework.trace import FrameworkTrace
    plan = AssemblyPlan(keyword="K", template_id="t", seed=0, slots=[
        SlotAssignment(slot_id="s1", picks=[]),
    ])
    fw = Framework(id="f", name="n", variables=[], blocks=[
        ParagraphBlock(kind="paragraph", slot="s1"),
    ])
    t = FrameworkTrace()
    out = compose_draft_framed(plan, fw, {}, trace=t)
    assert out == ""
    assert t.entries[0]["event"] == "skipped_empty_slot"
