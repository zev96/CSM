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
    # Hero title auto-appends plan.keyword ("k").
    assert compose_draft(p) == (
        "1. CEWEY DS18k\n\n推荐理由：\n理由 A\n\n理由 B"
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
    # Both hero and competitor titles auto-append plan.keyword ("k").
    assert out == (
        "1. CEWEY DS18k\n\n推荐理由：\n品牌背书\n\n"
        "2. 戴森V8k\n\n推荐理由：理由A\n\n"
        "3. 小狗T12k\n\n推荐理由：理由B"
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
    assert compose_draft(p) == "1. Ak\n\n推荐理由：r1\n\n2. Bk\n\n推荐理由：r2"


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
        "1. CEWEYk\n\n推荐理由：\n主段\n\n子变体"
    )


def test_paragraph_empty_picks_skipped():
    p = _plan(
        BlockResult(block_id="s1", kind="paragraph", picks=[]),
        BlockResult(block_id="s2", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="X")]),
    )
    assert compose_draft(p) == "X"


def test_chinese_style_hero_and_pool_no_extra_space():
    """Hero and competitor pool with Chinese style should have no space after prefix."""
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY",
                    meta={"number_style": "一、", "reason_label": "推荐理由："}),
        BlockResult(block_id="cp", kind="competitor_pool",
                    picks=[PickedVariant(note_id="n1", variant_index=0, text="理由",
                                         meta={"title": "戴森"})],
                    meta={"reason_label": "推荐理由："}),
    )
    assert compose_draft(p) == "一、CEWEYk\n\n推荐理由：\n\n二、戴森k\n\n推荐理由：理由"


def test_keyword_not_duplicated_when_title_already_ends_with_it():
    """Legacy templates that hard-code the keyword in the hero title
    shouldn't end up with '吸尘器吸尘器' after the auto-append rule."""
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY DS18无线吸尘器",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
    )
    p.keyword = "无线吸尘器"
    out = compose_draft(p)
    assert "CEWEY DS18无线吸尘器" in out
    assert "吸尘器吸尘器" not in out


def test_competitor_pool_inherits_hero_reason_label():
    """Competitor pool following hero uses hero's reason_label, not its
    own meta."""
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY",
                    meta={"number_style": "1.", "reason_label": "HERO_LABEL"}),
        BlockResult(block_id="cp", kind="competitor_pool",
                    picks=[PickedVariant(note_id="n1", variant_index=0,
                                         text="理由", meta={"title": "戴森"})],
                    meta={"reason_label": "POOL_LABEL"}),
    )
    out = compose_draft(p)
    assert "HERO_LABEL" in out
    assert "POOL_LABEL" not in out


def test_heading_index_with_builtin_separator_not_doubled():
    """序号填「一、」时不该再补一个顿号。

    模板编辑器里两种写法都很常见（出厂模板 导购·吸尘器·三品 里
    heading_kpaz 是 "一、"、heading_pv3o 是 "三"），历史实现无条件追加
    「、」，前者会渲染成 "## 一、、{keyword}怎么选"。
    """
    p = _plan(BlockResult(block_id="h", kind="heading", text="怎么选",
                          meta={"level": 2, "index": "一、"}))
    assert compose_draft(p) == "## 一、怎么选"


def test_heading_index_without_separator_still_gets_one():
    p = _plan(BlockResult(block_id="h", kind="heading", text="写在最后",
                          meta={"level": 2, "index": "三"}))
    assert compose_draft(p) == "## 三、写在最后"


def test_heading_index_accepts_other_separators():
    for idx, want in (
        ("1.", "## 1.正文"),
        ("（一）", "## （一）正文"),
        ("二：", "## 二：正文"),
        ("四 ", "## 四 正文"),      # 空格结尾也算已分隔
    ):
        p = _plan(BlockResult(block_id="h", kind="heading", text="正文",
                              meta={"level": 2, "index": idx}))
        assert compose_draft(p) == want, idx


def test_heading_blank_index_falls_back_to_plain():
    p = _plan(BlockResult(block_id="h", kind="heading", text="标题",
                          meta={"level": 2, "index": "  "}))
    assert compose_draft(p) == "## 标题"
