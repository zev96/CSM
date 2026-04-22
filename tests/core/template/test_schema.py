import pytest
from pydantic import ValidationError
from csm_core.template.schema import (
    Template, Slot, NotesQuerySource, BrandFixedSource,
    BrandPoolSource, TestResultsAlignedSource, PickCountSpec,
)


def test_template_minimal_valid():
    tpl = Template(
        id="t1",
        name="Test",
        product="吸尘器",
        slots=[
            Slot(
                id="intro",
                label="引言",
                source=NotesQuerySource(module="引言模块", filter={"组件类型": "痛点共鸣"}),
                pick_notes=1,
                pick_variants_per_note=1,
            ),
        ],
        render_order=["intro"],
    )
    assert tpl.id == "t1"
    assert len(tpl.slots) == 1


def test_render_order_must_match_slot_ids():
    with pytest.raises(ValidationError, match="render_order"):
        Template(
            id="t", name="T", product="吸尘器",
            slots=[Slot(
                id="a", label="A",
                source=NotesQuerySource(module="X"),
                pick_notes=1, pick_variants_per_note=1,
            )],
            render_order=["a", "b"],
        )


def test_depends_on_must_reference_existing_slot():
    with pytest.raises(ValidationError, match="depends_on"):
        Template(
            id="t", name="T", product="吸尘器",
            slots=[
                Slot(
                    id="a", label="A",
                    source=NotesQuerySource(module="X"),
                    pick_notes=1, pick_variants_per_note=1,
                    depends_on=["nonexistent"],
                ),
            ],
            render_order=["a"],
        )


def test_depends_on_must_be_acyclic():
    with pytest.raises(ValidationError, match="cycle"):
        Template(
            id="t", name="T", product="吸尘器",
            slots=[
                Slot(id="a", label="A",
                     source=NotesQuerySource(module="X"),
                     pick_notes=1, pick_variants_per_note=1,
                     depends_on=["b"]),
                Slot(id="b", label="B",
                     source=NotesQuerySource(module="X"),
                     pick_notes=1, pick_variants_per_note=1,
                     depends_on=["a"]),
            ],
            render_order=["a", "b"],
        )


def test_pick_count_random_between():
    spec = PickCountSpec.model_validate({"random_between": [3, 5]})
    assert spec.random_between == [3, 5]


def test_pick_count_user_configurable():
    spec = PickCountSpec.model_validate({
        "user_configurable": True, "default": 5, "range": [2, 9]
    })
    assert spec.default == 5
    assert spec.range == [2, 9]


def test_brand_fixed_source():
    s = BrandFixedSource(brand="CEWEY", model="CEWEYDS18")
    assert s.type == "brand_fixed"


def test_brand_pool_source():
    s = BrandPoolSource(exclude_brands=["CEWEY"])
    assert s.type == "brand_pool"


def test_test_results_aligned_source():
    s = TestResultsAlignedSource(
        follow_slot="brand_competitors",
        module="测试项目模块/品牌产品测试结果",
    )
    assert s.type == "test_results_aligned"


def test_template_default_framework_optional():
    t = Template(
        id="t", name="n", product="p",
        slots=[{
            "id": "s1", "label": "l",
            "source": {"type": "notes_query", "module": "m"},
        }],
        render_order=["s1"],
    )
    assert t.default_framework is None


def test_template_default_framework_roundtrip():
    t = Template(
        id="t", name="n", product="p",
        slots=[{
            "id": "s1", "label": "l",
            "source": {"type": "notes_query", "module": "m"},
        }],
        render_order=["s1"],
        default_framework="daogou-frame-v1",
    )
    assert t.default_framework == "daogou-frame-v1"
    dumped = t.model_dump()
    assert dumped["default_framework"] == "daogou-frame-v1"
