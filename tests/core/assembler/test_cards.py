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
    assert "榜单需要 9 个竞品" in msg and "本池可用 3 个" in msg
    assert "竞品" in msg


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


# ── 审查回归：区域语法 / 去重作用域 / 下游口径 ──────────────────────
def test_transition_paragraph_does_not_reset_ranking(tmp_path):
    """主推卡与竞品池之间插一句过渡段 —— 排位必须继续数，不能回到 TOP1。

    渲染与 lint 早期对「区」的定义不一致：渲染在段落处断区、lint 在标题处
    断区，结果是「插一句过渡段 → 竞品从 TOP1 重编号，而 lint 认定合法」。
    出厂导购模板恰恰就是 hero → 段落×3 → 竞品池 的形状。
    """
    _three_competitors(tmp_path)
    _hero_note(tmp_path, "主推/口碑.md", "市场口碑数据", "主推口碑")
    _hero_note(tmp_path, "P/t.md", "过渡", "下面看看这几款竞品")
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [{"label": "口碑", "filter": {"素材类型": "市场口碑数据"}}],
    }
    blocks = [
        hero,
        {"kind": "paragraph", "id": "trans", "label": "过渡",
         "source": {"type": "notes_query", "module": "P"}},
        _pool_block(pick=2),
    ]
    _, draft = _run(tmp_path, blocks)
    tops = [l.split("TOP")[1].split(".")[0]
            for l in draft.splitlines() if l.startswith("###")]
    assert tops == ["1", "2", "3"]
    assert "下面看看这几款竞品" in draft


def test_exclusion_resets_at_new_ranking_section(tmp_path):
    """两个独立榜单区（heading 隔开）各自自由排 —— 第一区不该扣光第二区。"""
    _three_competitors(tmp_path)
    blocks = [
        _pool_block(pick=3, block_id="p1"),
        {"kind": "heading", "id": "h", "level": 2, "text": "按预算再推荐"},
        _pool_block(pick=3, block_id="p2"),
    ]
    plan, _ = _run(tmp_path, blocks)
    assert len(plan.get_result("p1").meta["competitor_keys"]) == 3
    assert len(plan.get_result("p2").meta["competitor_keys"]) == 3


def test_shortfall_message_explains_pool_exclusion(tmp_path):
    """被前池抽光时不能报「目录里没有竞品卡」—— 目录里明明有。"""
    _three_competitors(tmp_path)
    with pytest.raises(CardRosterError) as e:
        _run(tmp_path, [_pool_block(pick=3, block_id="deep"),
                        _pool_block(pick=3, block_id="shallow")])
    msg = str(e.value)
    assert "名册合格 3 个" in msg and "已被本榜单前面的池选走" in msg
    assert "没有任何符合筛选条件" not in msg


def test_competitor_title_meta_stays_registry_shaped(tmp_path):
    """meta['title'] 必须是干净型号（下游按它查型号笔记），展示串走 display_title。"""
    _card(tmp_path, "竞品/竞品卡-米家3C.md", brand="米家", model="米家3C",
          sections={"市场口碑数据": ["甲"], "品牌赛道定位": ["乙"],
                    "分维度硬核测评": ["丙"]})
    plan, draft = _run(tmp_path, [_pool_block(pick=1)])
    pick = plan.results[0].picks[0]
    assert pick.meta["title"] == "米家3C"          # registry 口径
    assert pick.meta["brand"] == "小米"            # 别名折叠后的 canonical
    assert pick.meta["display_title"] == "小米 米家3C"
    assert "小米 米家3C" in draft                  # 渲染用展示串


def test_section_matching_does_not_strip_test_prefixes(tmp_path):
    """`## 测试数据` 不能被绑到「市场口碑数据」上。

    测试框架的匹配器会先剥「测试」前缀 → 「数据」，而「数据」是「市场口碑
    数据」的子串，一张没有口碑小节的卡就这样混过覆盖度预检。
    """
    _card(tmp_path, "竞品/竞品卡-诡异X.md", brand="诡异", model="诡异X1",
          sections={"测试数据": ["CADR 实测 480"], "品牌赛道定位": ["乙"],
                    "分维度硬核测评": ["丙"]})
    with pytest.raises(CardRosterError) as e:
        _run(tmp_path, [_pool_block(pick=1)])
    assert "市场口碑数据" in str(e.value)


def test_user_configurable_count_hard_fails_like_fixed(tmp_path):
    """UI 上填死的数量与写死的 int 一样是承诺，抽不满必须失败而不是静默少出。"""
    _three_competitors(tmp_path)
    pick = {"user_configurable": True, "default": 10, "range": [1, 10]}
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    with pytest.raises(CardRosterError):
        assemble_plan(
            keyword="空气净化器", template=_tpl([_pool_block(pick=pick)]),
            index=idx, registry=reg, seed=0, user_config={"pool": 10},
        )


def test_same_competitor_multiple_cards_are_alternatives(tmp_path):
    """同一竞品的多张合格卡互为候选（不是「第一张不行才用第二张」）。"""
    for suffix in ("A", "B"):
        _card(tmp_path, f"竞品/竞品卡-欧瑞达X9-{suffix}.md",
              brand="欧瑞达", model="欧瑞达X9",
              sections={"市场口碑数据": [f"{suffix} 版口碑"],
                        "品牌赛道定位": [f"{suffix} 版定位"],
                        "分维度硬核测评": [f"{suffix} 版测评"]})
    seen = set()
    for seed in range(12):
        plan, _ = _run(tmp_path, [_pool_block(pick=1)], seed=seed)
        seen.add(plan.results[0].picks[0].note_id)
    assert len(seen) == 2


def test_section_variants_are_not_repeated(tmp_path):
    """一个点抽 2 个候选时不该把同一段印两遍。"""
    _card(tmp_path, "竞品/竞品卡-多候选.md", brand="多", model="多X1",
          sections={"市场口碑数据": ["候选甲", "候选乙", "候选丙"],
                    "品牌赛道定位": ["定位"], "分维度硬核测评": ["测评"]})
    sections = [{"label": "市场口碑数据", "pick_variants": 2},
                {"label": "品牌赛道定位"}, {"label": "分维度硬核测评"}]
    plan, _ = _run(tmp_path, [_pool_block(pick=1, sections=sections)])
    texts = [p.text for p in plan.results[0].picks
             if p.meta["section_label"] == "市场口碑数据"]
    assert len(texts) == 2 and len(set(texts)) == 2


def test_near_duplicate_models_warn(tmp_path):
    """X9 与 X-9 两张全覆盖卡都会入册、各占一个排位 —— 必须告警。"""
    for model in ("欧瑞达X9", "欧瑞达X-9"):
        _card(tmp_path, f"竞品/竞品卡-{model}.md", brand="欧瑞达", model=model,
              sections={"市场口碑数据": ["甲"], "品牌赛道定位": ["乙"],
                        "分维度硬核测评": ["丙"]})
    plan, _ = _run(tmp_path, [_pool_block(pick=2)])
    assert any("疑似同款重复上榜" in w for w in plan.warnings)


def test_hero_card_capped_section_warns(tmp_path):
    """主推卡小节素材不够也要出告警，不能静默少一段。"""
    _hero_note(tmp_path, "主推/口碑.md", "市场口碑数据", "只有一篇")
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [{"label": "口碑", "filter": {"素材类型": "市场口碑数据"},
                      "pick_notes": 3}],
    }
    plan, _ = _run(tmp_path, [hero])
    assert any("素材不足" in w for w in plan.warnings)


def test_legacy_hero_does_not_swallow_card_pool(tmp_path):
    """legacy hero 收编卡片池会把 N 竞品×M 小节摊成 N×M 条编号项。"""
    _three_competitors(tmp_path)
    blocks = [
        {"kind": "hero_brand", "id": "hero", "title": "DARZ D9"},
        _pool_block(pick=2),
    ]
    _, draft = _run(tmp_path, blocks)
    assert draft.count("###") == 2          # 两张卡，不是 6 条编号项
    assert "3. " not in draft


def test_tier_conflict_warns(tmp_path):
    for i, tier in enumerate(("热门品牌", "性价比之选")):
        _card(tmp_path, f"竞品/竞品卡-欧瑞达X9-{i}.md", brand="欧瑞达",
              model="欧瑞达X9", tier=tier,
              sections={"市场口碑数据": ["甲"], "品牌赛道定位": ["乙"],
                        "分维度硬核测评": ["丙"]})
    plan, _ = _run(tmp_path, [_pool_block(pick=1)])
    assert any("层级标签不一致" in w for w in plan.warnings)


# ── 审查回归：缓存失效 / 报错可诊断 ─────────────────────────────────
def test_same_length_edit_is_picked_up(tmp_path):
    """等长订正必须立刻生效。

    ``550`` → ``660``、``口啤`` → ``口碑`` 这类改一个字的订正长度不变；
    早期缓存用「路径 + 正文长度」做 key，撞不到变化，已经改对的参数会继续
    被印进成稿直到进程重启。
    """
    _three_competitors(tmp_path)
    path = tmp_path / "竞品" / "竞品卡-欧瑞达X9.md"
    _, before = _run(tmp_path, [_pool_block(pick=3)])
    assert "欧瑞达X9 测评 **550m³/h**" in before

    path.write_text(
        path.read_text(encoding="utf-8").replace("550m³/h", "660m³/h"),
        encoding="utf-8",
    )
    _, after = _run(tmp_path, [_pool_block(pick=3)])   # 重新 scan_vault
    assert "欧瑞达X9 测评 **660m³/h**" in after
    assert "欧瑞达X9 测评 **550m³/h**" not in after


def test_section_cache_hits_within_one_build(tmp_path):
    """同一次建册里同一张卡不重复解析（缓存仍然有效，不是简单删掉）。"""
    from csm_core.assembler import cards
    from csm_core.vault.scanner import scan_vault

    _three_competitors(tmp_path)
    note = scan_vault(tmp_path).notes[0]
    first = cards.note_sections(note)
    assert cards.note_sections(note) is first          # 同一对象直接命中

    # 重新扫出来的是新对象 → 不共用缓存
    fresh = scan_vault(tmp_path).notes[0]
    assert cards.note_sections(fresh) is not first


def test_empty_pool_error_names_the_filter(tmp_path):
    """主推卡小节筛选值敲错时，报错要说清是哪个筛选没匹配上。"""
    from csm_core.assembler.sampler import EmptyPoolError

    _hero_note(tmp_path, "主推/口碑.md", "市场口碑数据", "正文")
    hero = {
        "kind": "hero_brand", "id": "hero", "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [{"label": "口碑", "filter": {"素材类型": "市场口碑"}}],
    }
    with pytest.raises(EmptyPoolError) as e:
        _run(tmp_path, [hero])
    assert "市场口碑" in str(e.value) and "主推" in str(e.value)


def test_tier_conflict_warning_says_it_varies(tmp_path):
    """多卡互为候选 → tier 每次随机，告警不能说「取首个」。"""
    for i, tier in enumerate(("热门品牌", "性价比之选")):
        _card(tmp_path, f"竞品/竞品卡-欧瑞达X9-{i}.md", brand="欧瑞达",
              model="欧瑞达X9", tier=tier,
              sections={"市场口碑数据": ["甲"], "品牌赛道定位": ["乙"],
                        "分维度硬核测评": ["丙"]})
    plan, _ = _run(tmp_path, [_pool_block(pick=1)])
    warn = next(w for w in plan.warnings if "层级标签不一致" in w)
    assert "随机" in warn and "按路径序取用" not in warn
