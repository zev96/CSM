import pytest
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.framework.schema import (
    Framework, ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
)
from csm_core.framework.renderer import (
    render_with_framework, FrameworkRenderError, FrameworkValidationError,
)
from csm_core.framework.trace import FrameworkTrace


def _plan(slots):
    return AssemblyPlan(keyword="k", template_id="t", seed=0, slots=slots)


def _pick(text, brand=None, model=None):
    meta = {}
    if brand: meta["brand"] = brand
    if model: meta["model"] = model
    return PickedVariant(note_id="n", variant_index=0, text=text, meta=meta)


def test_paragraph_joins_picks_with_blank_line():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[_pick("a"), _pick("b")])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[ParagraphBlock(kind="paragraph", slot="s1")])
    assert render_with_framework(plan, fw, {}) == "a\n\nb"


def test_heading_renders_markdown_with_index():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[HeadingBlock(kind="heading", level=2,
                                        index="一", text="怎么选")])
    assert render_with_framework(plan, fw, {}) == "## 一、怎么选"


def test_heading_without_index():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[HeadingBlock(kind="heading", level=3, text="小节")])
    assert render_with_framework(plan, fw, {}) == "### 小节"


def test_heading_variable_substitution():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[HeadingBlock(kind="heading", level=2,
                                        index="一", text="{keyword}怎么选")])
    assert render_with_framework(plan, fw, {"keyword": "吸尘器"}) \
        == "## 一、吸尘器怎么选"


def test_literal_emitted_verbatim():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[LiteralBlock(kind="literal", text="完。")])
    assert render_with_framework(plan, fw, {}) == "完。"


def test_literal_variable_substitution():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[LiteralBlock(kind="literal", text="欢迎选购{keyword}")])
    assert render_with_framework(plan, fw, {"keyword": "狗粮"}) == "欢迎选购狗粮"


def test_missing_required_variable_raises():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[HeadingBlock(kind="heading", level=2, text="{keyword}")])
    with pytest.raises(FrameworkRenderError):
        render_with_framework(plan, fw, {})


def test_unknown_slot_id_raises_validation_error():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[ParagraphBlock(kind="paragraph", slot="s_missing")])
    with pytest.raises(FrameworkValidationError):
        render_with_framework(plan, fw, {})


def test_blocks_joined_with_blank_lines():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[_pick("a")])])
    fw = Framework(id="f", name="n", variables=[], blocks=[
        HeadingBlock(kind="heading", level=2, text="H"),
        ParagraphBlock(kind="paragraph", slot="s1"),
    ])
    assert render_with_framework(plan, fw, {}) == "## H\n\na"


def test_numbered_list_renders_with_1based_index():
    plan = _plan([SlotAssignment(slot_id="s1",
                                  picks=[_pick("aa"), _pick("bb"), _pick("cc")])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[NumberedListBlock(kind="numbered_list", slot="s1")])
    assert render_with_framework(plan, fw, {}) == "1. aa\n2. bb\n3. cc"


def test_numbered_list_empty_slot_skipped_and_traced():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[NumberedListBlock(kind="numbered_list", slot="s1")])
    t = FrameworkTrace()
    assert render_with_framework(plan, fw, {}, trace=t) == ""
    assert t.entries == [
        {"event": "skipped_empty_slot", "slot_id": "s1", "block_index": 0}
    ]


def test_numbered_list_single_item():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[_pick("only"),])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[NumberedListBlock(kind="numbered_list", slot="s1")])
    assert render_with_framework(plan, fw, {}) == "1. only"


def test_brand_reason_list_continuous_numbering_across_slots():
    plan = _plan([
        SlotAssignment(slot_id="s_a", picks=[
            _pick("reason-a1", brand="B1", model="M1"),
            _pick("reason-a2", brand="B2", model="M2"),
        ]),
        SlotAssignment(slot_id="s_b", picks=[
            _pick("reason-b1", brand="B3", model="M3"),
        ]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["s_a", "s_b"])])
    out = render_with_framework(plan, fw, {"keyword": "吸尘器"})
    expected = (
        "1.B1 M1 吸尘器\n推荐理由：\nreason-a1\n\n"
        "2.B2 M2 吸尘器\n推荐理由：\nreason-a2\n\n"
        "3.B3 M3 吸尘器\n推荐理由：\nreason-b1"
    )
    assert out == expected


def test_brand_reason_list_custom_reason_label():
    plan = _plan([SlotAssignment(slot_id="s", picks=[
        _pick("why", brand="B", model="M"),
    ])])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(
                       kind="brand_reason_list", slots=["s"],
                       reason_label="核心卖点：",
                   )])
    out = render_with_framework(plan, fw, {"keyword": "K"})
    assert out == "1.B M K\n核心卖点：\nwhy"


def test_brand_reason_list_empty_sub_slot_continues_numbering():
    plan = _plan([
        SlotAssignment(slot_id="empty_slot", picks=[]),
        SlotAssignment(slot_id="s", picks=[
            _pick("w", brand="B", model="M"),
        ]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["empty_slot", "s"])])
    out = render_with_framework(plan, fw, {"keyword": "K"})
    assert out == "1.B M K\n推荐理由：\nw"


def test_brand_reason_list_all_empty_skipped_and_traced():
    plan = _plan([
        SlotAssignment(slot_id="a", picks=[]),
        SlotAssignment(slot_id="b", picks=[]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["a", "b"])])
    t = FrameworkTrace()
    out = render_with_framework(plan, fw, {"keyword": "K"}, trace=t)
    assert out == ""
    skipped = [e for e in t.entries if e["event"] == "skipped_empty_slot"]
    assert len(skipped) == 2


def test_brand_reason_list_missing_meta_falls_back_and_traces():
    plan = _plan([SlotAssignment(slot_id="s", picks=[
        _pick("w"),  # no brand / model
    ])])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["s"])])
    t = FrameworkTrace()
    out = render_with_framework(plan, fw, {"keyword": "K"}, trace=t)
    assert out == "1.w"
    missing = [e for e in t.entries if e["event"] == "missing_meta"]
    assert len(missing) == 1
    assert set(missing[0]["missing_keys"]) == {"brand", "model"}
