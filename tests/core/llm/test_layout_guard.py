"""卡片排版守卫：只保护卡片区结构，不误伤正常润色。"""
from csm_core.llm import layout_guard
from csm_core.llm.layout_guard import CardSignature
from csm_core.llm.prompts import PromptInputs, build_prompt, build_refine_prompt

_SIG = CardSignature(
    titles=("霍尼韦尔 H-Max", "欧瑞达X9"),
    labels=("市场口碑数据", "品牌赛道定位"),
)

_DOC = """## 一、前言

这是引言第一段。

这是引言第二段。

### 国内外知名品牌-综合性能首选 TOP1. 霍尼韦尔 H-Max

**市场口碑数据** ：全球500强，天猫五项TOP1。

**品牌赛道定位** ：航空级技术民用化旗舰。

### 热门品牌 TOP2. 欧瑞达X9

**市场口碑数据** ：销量稳步增长。

**品牌赛道定位** ：主打长效滤网。"""


def _check(after: str) -> str | None:
    return layout_guard.check(_DOC, after, _SIG)


# ── 该拦的 ──────────────────────────────────────────────────────────
def test_flattened_card_headings_rejected():
    assert "卡片标题行" in _check(_DOC.replace("### ", ""))


def test_renamed_card_heading_rejected():
    assert _check(_DOC.replace("TOP2. 欧瑞达X9", "第二名 欧瑞达X9")) is not None


def test_dropped_card_label_rejected():
    assert "加粗小节" in _check(_DOC.replace("**品牌赛道定位** ：", "", 1))


def test_dropped_whole_card_rejected():
    cut = _DOC.split("### 热门品牌")[0]
    assert _check(cut) is not None


def test_reordered_cards_rejected():
    head, cards = _DOC.split("### ", 1)
    first, second = ("### " + cards).split("\n\n### ")
    swapped = head + "### " + second + "\n\n" + first
    assert _check(swapped) is not None


# ── 不该拦的（旧版全文指纹会误伤，导致整轮润色作废）────────────────
def test_wording_polish_passes():
    assert _check(_DOC.replace("销量稳步增长", "销量一路走高，口碑扎实")) is None


def test_merging_non_card_paragraphs_passes():
    merged = _DOC.replace("这是引言第一段。\n\n这是引言第二段。", "引言合并成一段。")
    assert _check(merged) is None


def test_rewriting_non_card_heading_passes():
    assert _check(_DOC.replace("## 一、前言", "## 一、写在前面")) is None


def test_llm_adding_a_heading_passes():
    grown = _DOC + "\n\n## 三、写在最后\n\n收尾段落。"
    assert _check(grown) is None


def test_inline_bold_in_body_is_not_a_section_label():
    """正文里 **703.7 m³/h** 这类数据标粗不是小节名，改写它不该被拦。"""
    a = _DOC.replace("销量稳步增长。", "**550m³/h** 的洁净空气量表现稳定。")
    b = _DOC.replace("销量稳步增长。", "洁净空气量高达 **550m³/h**，表现稳定。")
    assert layout_guard.check(a, b, _SIG) is None


def test_no_signature_means_no_guard():
    """没有卡片区的文章：守卫不启用，任何改写都放行（零回归）。"""
    assert layout_guard.check(_DOC, "彻底重写成一段话。", None) is None
    assert layout_guard.check(_DOC, "彻底重写。", CardSignature()) is None


# ── 签名提取 ────────────────────────────────────────────────────────
def test_signature_from_plan_collects_titles_and_labels():
    from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant

    hero = BlockResult(
        block_id="hero", kind="hero_brand", text="霍尼韦尔 H-Max",
        meta={"card": True, "section_labels": ["市场口碑数据", ""]},
    )
    pool = BlockResult(
        block_id="pool", kind="competitor_pool",
        meta={"card": True},
        picks=[PickedVariant(
            note_id="n", variant_index=0, text="x",
            meta={"display_title": "欧瑞达 X9", "title": "X9",
                  "section_label": "品牌赛道定位"},
        )],
    )
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0,
                        results=[hero, pool])
    sig = layout_guard.signature_from_plan(plan)
    assert "霍尼韦尔 H-Max" in sig.titles
    assert "欧瑞达 X9" in sig.titles        # 展示串优先
    assert set(sig.labels) == {"市场口碑数据", "品牌赛道定位"}
    assert "" not in sig.labels


def test_signature_empty_for_legacy_plan():
    from csm_core.assembler.plan import AssemblyPlan, BlockResult

    plan = AssemblyPlan(
        keyword="k", template_id="t", seed=0,
        results=[BlockResult(block_id="p", kind="paragraph")],
    )
    assert not layout_guard.signature_from_plan(plan)


# ── prompt 条款 ─────────────────────────────────────────────────────
def test_prompt_clause_only_when_enabled():
    base = PromptInputs(user_skill_prompt="s", keyword="空气净化器", draft=_DOC)
    _, plain = build_prompt(base)
    assert layout_guard.LAYOUT_CLAUSE not in plain
    base.preserve_layout = True
    _, guarded = build_prompt(base)
    assert layout_guard.LAYOUT_CLAUSE in guarded


def test_refine_prompt_clause_opt_in():
    _, plain = build_refine_prompt("s", _DOC)
    assert layout_guard.LAYOUT_CLAUSE not in plain
    _, guarded = build_refine_prompt("s", _DOC, preserve_layout=True)
    assert layout_guard.LAYOUT_CLAUSE in guarded
