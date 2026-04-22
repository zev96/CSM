import pytest
from csm_core.template.schema import Template


def _min_tpl(**blocks):
    return {
        "id": "t1", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": list(blocks.get("blocks", [])),
    }


def test_paragraph_block_roundtrips():
    d = _min_tpl(blocks=[{
        "kind": "paragraph", "id": "s1", "label": "痛点",
        "source": {"type": "notes_query", "module": "吸尘器/痛点"},
        "pick_notes": 1, "pick_variants_per_note": 1,
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].kind == "paragraph"
    assert tpl.blocks[0].id == "s1"


def test_heading_block_requires_text():
    d = _min_tpl(blocks=[{"kind": "heading", "id": "h1", "level": 2}])
    with pytest.raises(Exception):
        Template.model_validate(d)


def test_numbered_list_defaults():
    d = _min_tpl(blocks=[{
        "kind": "numbered_list", "id": "n1", "label": "科普",
        "source": {"type": "notes_query", "module": "吸尘器/科普"},
    }])
    tpl = Template.model_validate(d)
    b = tpl.blocks[0]
    assert b.number_style == "1."
    assert b.pick_notes == 3
    assert b.item_separator == "\n\n"


def test_hero_brand_literal_title():
    d = _min_tpl(blocks=[{
        "kind": "hero_brand", "id": "h1",
        "title": "CEWEY DS18", "number_style": "1.",
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].title == "CEWEY DS18"
    assert tpl.blocks[0].reason_label == "推荐理由："


def test_competitor_pool_source_required():
    d = _min_tpl(blocks=[{
        "kind": "competitor_pool", "id": "c1",
        "source": {"type": "notes_query", "module": "吸尘器/竞品"},
        "pick_notes": {"random_between": [2, 2]},
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].pick_notes.random_between == [2, 2]


def test_literal_block_roundtrips():
    d = _min_tpl(blocks=[{"kind": "literal", "id": "l1", "text": "完。"}])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].text == "完。"


def test_paragraph_children_flat_list():
    d = _min_tpl(blocks=[{
        "kind": "paragraph", "id": "s6", "label": "品牌背书",
        "source": {"type": "notes_query", "module": "希喂/品牌背书"},
        "children": [
            {
                "kind": "paragraph", "id": "s6_1", "label": "海外口碑",
                "source": {"type": "notes_query", "module": "希喂/品牌背书"},
            }
        ],
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].children[0].id == "s6_1"


def test_template_rejects_unknown_kind():
    d = _min_tpl(blocks=[{"kind": "bogus", "id": "x"}])
    with pytest.raises(Exception):
        Template.model_validate(d)


def test_blocks_must_be_nonempty():
    with pytest.raises(Exception):
        Template.model_validate(_min_tpl(blocks=[]))


def test_duplicate_block_ids_rejected():
    d = _min_tpl(blocks=[
        {"kind": "literal", "id": "x", "text": "a"},
        {"kind": "literal", "id": "x", "text": "b"},
    ])
    with pytest.raises(ValueError, match="duplicate"):
        Template.model_validate(d)
