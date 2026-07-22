"""榜单卡片：名册/覆盖度/采样/渲染/跨池去重/加粗保真。"""
from pathlib import Path

import pytest

from csm_core.assembler.cards import CardRosterError
from csm_core.assembler.constraints import assemble_plan
from csm_core.assembler.render import compose_draft
from csm_core.brand_memory.identity import normalize_model_key
from csm_core.template.schema import Template
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault.scanner import scan_vault


# ── vault 脚手架 ────────────────────────────────────────────────────
def _card(vault: Path, rel: str, *, brand: str, model: str,
          tier: str = "热门品牌", sections: dict[str, list[str]],
          material_type: str = "竞品卡") -> None:
    body = "\n\n".join(
        f"## {h2}\n" + "\n".join(f"{m} {t}" for m, t in zip("①②③④", variants))
        for h2, variants in sections.items()
    )
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\n品牌: {brand}\n型号: {model}\n素材类型: {material_type}\n"
        f"层级标签: {tier}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _hero_note(vault: Path, rel: str, kind: str, *variants: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{m} {t}" for m, t in zip("①②③④", variants))
    p.write_text(
        f"---\n产品: 空气净化器\n素材类型: {kind}\n---\n\n{body}\n",
        encoding="utf-8",
    )


_SECTIONS = [
    {"label": "市场口碑数据"},
    {"label": "品牌赛道定位"},
    {"label": "分维度硬核测评"},
]


def _pool_block(pick=2, sections=None, block_id="pool", **extra):
    return {
        "kind": "competitor_pool", "id": block_id,
        "source": {"type": "notes_query", "module": "竞品",
                   "filter": {"素材类型": "竞品卡"}},
        "pick_notes": pick,
        "sections": sections if sections is not None else _SECTIONS,
        **extra,
    }


def _tpl(blocks):
    return Template.model_validate({
        "id": "t", "name": "T", "product": "空气净化器", "blocks": blocks,
    })


def _run(tmp_path, blocks, seed=0, keyword="空气净化器"):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    plan = assemble_plan(
        keyword=keyword, template=_tpl(blocks), index=idx, registry=reg,
        seed=seed, user_config={},
    )
    return plan, compose_draft(plan)


def _three_competitors(tmp_path: Path) -> None:
    for i, (brand, model) in enumerate(
        [("欧瑞达", "欧瑞达X9"), ("亚都", "亚都KJ500"), ("树新风", "树新风A1")]
    ):
        _card(tmp_path, f"竞品/竞品卡-{model}.md", brand=brand, model=model,
              sections={
                  "市场口碑数据": [f"{model} 口碑甲", f"{model} 口碑乙"],
                  "品牌赛道定位": [f"{model} 定位"],
                  "分维度硬核测评": [f"{model} 测评 **550m³/h**，短板是没有认证"],
              })


# ── 身份归一 ────────────────────────────────────────────────────────
def test_normalize_model_key_folds_prefix_case_width_space():
    assert normalize_model_key("竞品-戴森V8") == normalize_model_key("戴森V8")
    assert normalize_model_key("戴森 V8") == normalize_model_key("戴森V8")
    assert normalize_model_key("戴森ｖ8") == normalize_model_key("戴森V8")
    # 连字符不折叠 —— V8-Pro 与 V8Pro 可能是两款货
    assert normalize_model_key("戴森V8-Pro") != normalize_model_key("戴森V8Pro")


def test_inconsistent_model_spelling_stays_one_competitor(tmp_path):
    """同一竞品两张卡型号写法不同（带/不带 竞品- 前缀）→ 仍是一个竞品。"""
    _card(tmp_path, "竞品/竞品卡-欧瑞达X9.md", brand="欧瑞达", model="竞品-欧瑞达X9",
          sections={"市场口碑数据": ["甲"], "品牌赛道定位": ["乙"],
                    "分维度硬核测评": ["丙"]})
    _card(tmp_path, "竞品/竞品卡-欧瑞达X9-备.md", brand="欧瑞达", model="欧瑞达 X9",
          sections={"市场口碑数据": ["甲2"], "品牌赛道定位": ["乙2"],
                    "分维度硬核测评": ["丙2"]})
    plan, _ = _run(tmp_path, [_pool_block(pick=1)])
    keys = plan.results[0].meta["competitor_keys"]
    assert len(keys) == 1
    # 名册里只有一个竞品，请求 2 个就该硬失败
    with pytest.raises(CardRosterError):
        _run(tmp_path, [_pool_block(pick=2)])


# ── 覆盖度预检 ──────────────────────────────────────────────────────
def test_missing_required_section_excluded_with_actionable_warning(tmp_path):
    _three_competitors(tmp_path)
    _card(tmp_path, "竞品/竞品卡-半残X.md", brand="半残", model="半残X",
          sections={"市场口碑数据": ["只有口碑"]})
    plan, _ = _run(tmp_path, [_pool_block(pick=3)])
    assert "半残X" not in str(plan.results[0].meta["competitor_keys"])
    warn = "\n".join(plan.warnings)
    assert "半残X" in warn and "品牌赛道定位" in warn


def test_missing_frontmatter_warning_carries_full_path(tmp_path):
    _three_competitors(tmp_path)
    p = tmp_path / "竞品" / "竞品卡-无名.md"
    p.write_text(
        "---\n素材类型: 竞品卡\n---\n\n## 市场口碑数据\n① 甲\n",
        encoding="utf-8",
    )
    plan, _ = _run(tmp_path, [_pool_block(pick=3)])
    warn = "\n".join(plan.warnings)
    assert "竞品卡-无名.md" in warn and "缺 品牌/型号" in warn


def test_optional_section_absent_is_skipped_not_excluded(tmp_path):
    _three_competitors(tmp_path)
    sections = _SECTIONS + [{"label": "横评总结点评", "required": False}]
    plan, draft = _run(tmp_path, [_pool_block(pick=3, sections=sections)])
    assert len(plan.results[0].meta["competitor_keys"]) == 3
    assert "横评总结点评" not in draft


# ── 硬失败语义 ──────────────────────────────────────────────────────
def test_fixed_count_shortfall_hard_fails_with_checklist(tmp_path):
    _three_competitors(tmp_path)
    with pytest.raises(CardRosterError) as e:
        _run(tmp_path, [_pool_block(pick=9)])
    msg = str(e.value)
    assert "榜单需要 9 个竞品" in msg and "只有 3 个" in msg


def test_random_between_clamps_with_warning(tmp_path):
    _three_competitors(tmp_path)
    plan, _ = _run(tmp_path, [_pool_block(pick={"random_between": [8, 9]})])
    assert len(plan.results[0].meta["competitor_keys"]) == 3
    assert any("名册仅 3 个可用" in w for w in plan.warnings)


def test_empty_roster_error_names_the_block(tmp_path):
    _hero_note(tmp_path, "竞品/无关.md", "别的类型", "x")
    with pytest.raises(CardRosterError) as e:
        _run(tmp_path, [_pool_block(pick=2)])
    assert "block 'pool'" in str(e.value)


# ── 渲染 ────────────────────────────────────────────────────────────
def test_card_rendering_matches_user_format(tmp_path):
    _three_competitors(tmp_path)
    _hero_note(tmp_path, "主推/口碑.md", "市场口碑数据", "DARZ 口碑正文")
    _hero_note(tmp_path, "主推/定位.md", "品牌赛道定位", "DARZ 定位正文")
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "tier": "国内外知名品牌-综合性能首选",
        "heading_template": "### {tier} TOP{n}. {title}",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [
            {"label": "市场口碑数据", "filter": {"素材类型": "市场口碑数据"}},
            {"label": "品牌赛道定位", "filter": {"素材类型": "品牌赛道定位"}},
        ],
    }
    plan, draft = _run(tmp_path, [hero, _pool_block(pick=2)])
    lines = [l for l in draft.splitlines() if l.startswith("###")]
    assert lines[0] == "### 国内外知名品牌-综合性能首选 TOP1. DARZ D9"
    assert lines[1].startswith("### 热门品牌 TOP2. ")
    assert lines[2].startswith("### 热门品牌 TOP3. ")
    assert "**市场口碑数据** ：DARZ 口碑正文" in draft
    # 卡片标题不追加产品关键词（范文是「TOP2. 欧瑞达X9」不是「…空气净化器」）
    assert "空气净化器 TOP" not in draft
    assert "推荐理由：" not in draft


def test_inline_bold_survives_into_card(tmp_path):
    """素材里的 **550m³/h** 必须原样进正文 —— 解析器默认会剥光加粗。"""
    _three_competitors(tmp_path)
    _, draft = _run(tmp_path, [_pool_block(pick=2)])
    assert "**550m³/h**" in draft


def test_legacy_paths_still_strip_bold(tmp_path):
    """老路径（段落）行为不变：加粗照旧剥掉。"""
    _hero_note(tmp_path, "P/a.md", "引言", "普通段落 **加粗数据** 尾巴")
    _, draft = _run(tmp_path, [{
        "kind": "paragraph", "id": "p", "label": "P",
        "source": {"type": "notes_query", "module": "P"},
    }])
    assert "加粗数据" in draft and "**" not in draft


def test_label_layout_line_puts_label_on_own_line(tmp_path):
    _three_competitors(tmp_path)
    _, draft = _run(tmp_path, [_pool_block(pick=1, label_layout="line")])
    assert "**市场口碑数据**\n" in draft


def test_empty_label_section_renders_as_continuation(tmp_path):
    """一个点拆多段：只有首段带加粗标题，后续段落纯正文。"""
    _hero_note(tmp_path, "主推/除醛.md", "除醛维度", "除醛正文")
    _hero_note(tmp_path, "主推/消毒.md", "消毒维度", "消毒正文")
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [
            {"label": "分维度硬核测评", "filter": {"素材类型": "除醛维度"}},
            {"label": "", "filter": {"素材类型": "消毒维度"}},
        ],
    }
    _, draft = _run(tmp_path, [hero])
    assert "**分维度硬核测评** ：除醛正文" in draft
    assert "\n\n消毒正文" in draft
    assert draft.count("**") == 2      # 只有一个加粗标签


# ── 跨池去重 + 连续编号 ─────────────────────────────────────────────
def test_two_pools_continue_numbering_without_duplicates(tmp_path):
    _three_competitors(tmp_path)
    for brand, model in [("A牌", "A1"), ("B牌", "B1"), ("C牌", "C1")]:
        _card(tmp_path, f"竞品/竞品卡-{model}.md", brand=brand, model=model,
              sections={"市场口碑数据": [f"{model} 口碑"],
                        "品牌赛道定位": [f"{model} 定位"],
                        "分维度硬核测评": [f"{model} 测评"]})
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [{"label": "口碑", "filter": {"素材类型": "市场口碑数据"}}],
    }
    _hero_note(tmp_path, "主推/口碑.md", "市场口碑数据", "主推口碑")
    deep = _pool_block(pick=2, block_id="deep")
    shallow = _pool_block(
        pick=3, block_id="shallow",
        sections=[{"label": "市场口碑数据"}],
    )
    plan, draft = _run(tmp_path, [hero, deep, shallow])
    tops = [l for l in draft.splitlines() if l.startswith("###")]
    assert [t.split("TOP")[1].split(".")[0] for t in tops] == [
        "1", "2", "3", "4", "5", "6",
    ]
    deep_keys = set(plan.get_result("deep").meta["competitor_keys"])
    shallow_keys = set(plan.get_result("shallow").meta["competitor_keys"])
    assert deep_keys.isdisjoint(shallow_keys)


def test_card_region_counter_does_not_leak_across_headings(tmp_path):
    _three_competitors(tmp_path)
    blocks = [
        _pool_block(pick=1, block_id="p1"),
        {"kind": "heading", "id": "h", "level": 2, "text": "另一节"},
        _pool_block(pick=1, block_id="p2"),
    ]
    _, draft = _run(tmp_path, blocks)
    tops = [l for l in draft.splitlines() if l.startswith("###")]
    assert all("TOP1." in t for t in tops)


# ── 确定性 ──────────────────────────────────────────────────────────
def test_same_seed_reproduces_identical_draft(tmp_path):
    _three_competitors(tmp_path)
    a = _run(tmp_path, [_pool_block(pick=2)], seed=4)[1]
    b = _run(tmp_path, [_pool_block(pick=2)], seed=4)[1]
    assert a == b


# ── 卡片 reroll ─────────────────────────────────────────────────────
def _reroll(tmp_path, blocks, block_id, pick_index, seed=0):
    import random
    from csm_core.assembler.reroll import reroll_pick
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    tpl = _tpl(blocks)
    plan = assemble_plan(
        keyword="空气净化器", template=tpl, index=idx, registry=reg,
        seed=seed, user_config={},
    )
    new = reroll_pick(plan, block_id, pick_index, tpl, idx,
                      rng=random.Random(1))
    return plan, new


def test_competitor_reroll_stays_in_same_competitor_and_section(tmp_path):
    """默认 reroll 会按块级 source 重建整目录池 —— 卡片必须锁死在同竞品同小节。"""
    _three_competitors(tmp_path)
    old, new = _reroll(tmp_path, [_pool_block(pick=2)], "pool", 0)
    a = old.get_result("pool").picks[0]
    b = new.get_result("pool").picks[0]
    assert b.text != a.text                       # 真的换了
    assert b.meta["competitor_key"] == a.meta["competitor_key"]
    assert b.meta["section_label"] == a.meta["section_label"]
    assert b.meta["title"] == a.meta["title"]     # 卡片 meta 全量保留
    # 其他 pick 不动
    assert new.get_result("pool").picks[1].text == old.get_result("pool").picks[1].text


def test_competitor_reroll_without_alternatives_raises(tmp_path):
    from csm_core.assembler.reroll import NoCandidatesError
    _card(tmp_path, "竞品/竞品卡-独苗.md", brand="独苗", model="独苗X1",
          sections={"市场口碑数据": ["唯一候选"], "品牌赛道定位": ["定位"],
                    "分维度硬核测评": ["测评"]})
    with pytest.raises(NoCandidatesError, match="没有其他候选"):
        _reroll(tmp_path, [_pool_block(pick=1)], "pool", 0)


def test_hero_card_reroll_stays_in_same_section(tmp_path):
    _hero_note(tmp_path, "主推/口碑1.md", "市场口碑数据", "口碑甲", "口碑乙")
    _hero_note(tmp_path, "主推/定位1.md", "品牌赛道定位", "定位甲", "定位乙")
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [
            {"label": "市场口碑数据", "filter": {"素材类型": "市场口碑数据"}},
            {"label": "品牌赛道定位", "filter": {"素材类型": "品牌赛道定位"}},
        ],
    }
    old, new = _reroll(tmp_path, [hero], "hero", 0)
    a, b = old.get_result("hero").picks[0], new.get_result("hero").picks[0]
    assert b.text != a.text
    assert b.text.startswith("口碑")             # 没串到定位小节
    assert b.meta["section_label"] == "市场口碑数据"


def test_reroll_preserves_bold_in_cards(tmp_path):
    _three_competitors(tmp_path)
    _card(tmp_path, "竞品/竞品卡-欧瑞达X9b.md", brand="欧瑞达", model="欧瑞达X9",
          sections={
              "市场口碑数据": ["另一张卡的口碑 **99.9%**"],
              "品牌赛道定位": ["定位"], "分维度硬核测评": ["测评"],
          })
    old, new = _reroll(tmp_path, [_pool_block(pick=3)], "pool", 0)
    texts = [p.text for p in new.get_result("pool").picks]
    assert any("**" in t for t in texts)
