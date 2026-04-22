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
