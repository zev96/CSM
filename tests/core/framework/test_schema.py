import pytest
from pydantic import ValidationError
from csm_core.framework.schema import (
    Framework, ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
)


def test_framework_minimal_valid():
    fw = Framework(
        id="f1", name="n", variables=[],
        blocks=[ParagraphBlock(kind="paragraph", slot="s1")],
    )
    assert fw.id == "f1"
    assert fw.blocks[0].slot == "s1"


def test_heading_supports_level_and_index():
    h = HeadingBlock(kind="heading", level=2, index="一", text="{keyword}怎么选")
    assert h.level == 2 and h.index == "一"


def test_brand_reason_list_requires_slots_non_empty():
    with pytest.raises(ValidationError):
        BrandReasonListBlock(kind="brand_reason_list", slots=[])


def test_literal_requires_text():
    with pytest.raises(ValidationError):
        LiteralBlock(kind="literal", text="")


def test_numbered_list_requires_slot():
    with pytest.raises(ValidationError):
        NumberedListBlock(kind="numbered_list", slot="")


def test_framework_rejects_unknown_variable_in_heading_text():
    with pytest.raises(ValidationError) as ei:
        Framework(
            id="f1", name="n", variables=["keyword"],
            blocks=[HeadingBlock(kind="heading", level=2, text="{unknown}")],
        )
    assert "unknown" in str(ei.value).lower()


def test_framework_rejects_unknown_variable_in_literal_text():
    with pytest.raises(ValidationError):
        Framework(
            id="f1", name="n", variables=[],
            blocks=[LiteralBlock(kind="literal", text="{keyword}!")],
        )


def test_framework_allows_declared_variable_in_heading_and_literal():
    fw = Framework(
        id="f1", name="n", variables=["keyword"],
        blocks=[
            HeadingBlock(kind="heading", level=2, text="{keyword}"),
            LiteralBlock(kind="literal", text="完。"),
        ],
    )
    assert len(fw.blocks) == 2


def test_heading_level_must_be_1_2_or_3():
    with pytest.raises(ValidationError):
        HeadingBlock(kind="heading", level=5, text="x")
