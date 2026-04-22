from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.assembler.render import compose_draft


def _plan(*results):
    return AssemblyPlan(keyword="k", template_id="t", seed=0, results=list(results))


def test_plain_paragraph_and_heading():
    p = _plan(
        BlockResult(block_id="h", kind="heading", text="题",
                    meta={"level": 2, "index": "一"}),
        BlockResult(block_id="s", kind="paragraph",
                    picks=[PickedVariant(note_id="n", variant_index=0, text="段落正文")]),
    )
    out = compose_draft(p)
    assert out == "## 一、题\n\n段落正文"


def test_literal_substitutes_keyword():
    p = _plan(BlockResult(block_id="l", kind="literal", text="关于 {keyword}"))
    p.keyword = "吸尘器"
    assert compose_draft(p) == "关于 吸尘器"


def test_numbered_list_formats_with_number_style():
    p = _plan(BlockResult(
        block_id="n", kind="numbered_list",
        picks=[
            PickedVariant(note_id="a", variant_index=0, text="aaa"),
            PickedVariant(note_id="b", variant_index=0, text="bbb"),
            PickedVariant(note_id="c", variant_index=0, text="ccc"),
        ],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    assert compose_draft(p) == "1. aaa\n\n2. bbb\n\n3. ccc"


def test_hero_brand_without_pool_renders_standalone():
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY DS18",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
        BlockResult(block_id="p1", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="理由 A")]),
        BlockResult(block_id="p2", kind="paragraph",
                    picks=[PickedVariant(note_id="b", variant_index=0, text="理由 B")]),
    )
    assert compose_draft(p) == (
        "1. CEWEY DS18\n推荐理由：\n理由 A\n\n理由 B"
    )


def test_hero_brand_closed_by_competitor_pool_continuous_numbering():
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY DS18",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
        BlockResult(block_id="p1", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="品牌背书")]),
        BlockResult(block_id="cp", kind="competitor_pool",
                    picks=[
                        PickedVariant(note_id="n1", variant_index=0, text="理由A",
                                      meta={"title": "戴森V8"}),
                        PickedVariant(note_id="n2", variant_index=0, text="理由B",
                                      meta={"title": "小狗T12"}),
                    ],
                    meta={"reason_label": "推荐理由："}),
    )
    out = compose_draft(p)
    assert out == (
        "1. CEWEY DS18\n推荐理由：\n品牌背书\n\n"
        "2. 戴森V8\n推荐理由：理由A\n\n"
        "3. 小狗T12\n推荐理由：理由B"
    )


def test_competitor_pool_standalone_starts_from_one():
    p = _plan(BlockResult(
        block_id="cp", kind="competitor_pool",
        picks=[
            PickedVariant(note_id="n1", variant_index=0, text="r1",
                          meta={"title": "A"}),
            PickedVariant(note_id="n2", variant_index=0, text="r2",
                          meta={"title": "B"}),
        ],
        meta={"reason_label": "推荐理由："},
    ))
    assert compose_draft(p) == "1. A\n推荐理由：r1\n\n2. B\n推荐理由：r2"


def test_chinese_number_style():
    p = _plan(BlockResult(
        block_id="n", kind="numbered_list",
        picks=[PickedVariant(note_id="a", variant_index=0, text="x"),
               PickedVariant(note_id="b", variant_index=0, text="y")],
        meta={"number_style": "一、", "item_separator": "\n\n"},
    ))
    assert compose_draft(p) == "一、x\n\n二、y"


def test_paragraph_children_flatten_into_region():
    """Sub-variants under a paragraph render as additional paragraph body."""
    child = BlockResult(
        block_id="p1_1", kind="paragraph",
        picks=[PickedVariant(note_id="c", variant_index=0, text="子变体")],
    )
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
        BlockResult(
            block_id="p1", kind="paragraph",
            picks=[PickedVariant(note_id="p", variant_index=0, text="主段")],
            children=[child],
        ),
    )
    assert compose_draft(p) == (
        "1. CEWEY\n推荐理由：\n主段\n\n子变体"
    )


def test_paragraph_empty_picks_skipped():
    p = _plan(
        BlockResult(block_id="s1", kind="paragraph", picks=[]),
        BlockResult(block_id="s2", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="X")]),
    )
    assert compose_draft(p) == "X"
