"""卡片排版守卫：结构指纹比对 + prompt 硬约束。"""
from csm_core.llm import layout_guard
from csm_core.llm.prompts import PromptInputs, build_prompt, build_refine_prompt

_CARD = """### 国内外知名品牌-综合性能首选 TOP1. 霍尼韦尔 H-Max

**市场口碑数据** ：全球500强，天猫五项TOP1。

**品牌赛道定位** ：航空级技术民用化旗舰。

### 热门品牌 TOP2. 欧瑞达X9

**市场口碑数据** ：销量稳步增长。

**品牌赛道定位** ：主打长效滤网。"""


def test_wording_only_polish_passes():
    polished = _CARD.replace("销量稳步增长", "销量一路走高，口碑扎实")
    assert layout_guard.check(_CARD, polished) is None


def test_flattened_headings_rejected():
    flat = _CARD.replace("### ", "")
    assert "标题行" in layout_guard.check(_CARD, flat)


def test_renamed_heading_rejected():
    renamed = _CARD.replace("TOP2. 欧瑞达X9", "第二名 欧瑞达X9")
    assert layout_guard.check(_CARD, renamed) is not None


def test_dropped_bold_label_rejected():
    dropped = _CARD.replace("**品牌赛道定位** ：", "")
    assert layout_guard.check(_CARD, dropped) is not None


def test_merged_paragraphs_rejected():
    merged = _CARD.replace("\n\n", "\n")
    assert layout_guard.check(_CARD, merged) is not None


def test_added_paragraph_is_allowed():
    """扩写不算破坏结构 —— 只要标题与小节都在、段落没被合并。"""
    grown = _CARD + "\n\n补充一段说明。"
    assert layout_guard.check(_CARD, grown) is None


def test_prompt_clause_only_when_enabled():
    base = PromptInputs(
        user_skill_prompt="s", keyword="空气净化器", draft=_CARD,
    )
    _, plain = build_prompt(base)
    assert layout_guard.LAYOUT_CLAUSE not in plain

    base.preserve_layout = True
    _, guarded = build_prompt(base)
    assert layout_guard.LAYOUT_CLAUSE in guarded


def test_refine_prompt_clause_opt_in():
    _, plain = build_refine_prompt("s", _CARD)
    assert layout_guard.LAYOUT_CLAUSE not in plain
    _, guarded = build_refine_prompt("s", _CARD, preserve_layout=True)
    assert layout_guard.LAYOUT_CLAUSE in guarded
