"""模板结构 lint —— 版本标签防错层。"""
import pytest

from csm_core.template.lint import has_errors, lint_template
from csm_core.template.schema import Template

_GROUP = [{"id": "ver", "options": ["版本1", "版本2"]}]


def _tpl(blocks, groups=None):
    payload = {"id": "t", "name": "T", "product": "吸尘器", "blocks": blocks}
    if groups is not None:
        payload["version_groups"] = groups
    return Template.model_validate(payload)


def _codes(tpl):
    return {i.code for i in lint_template(tpl)}


def _src(module="M"):
    return {"type": "notes_query", "module": module}


# ── 引用完整性（schema 层，直接 raise）────────────────────────────────
def test_unknown_option_rejected():
    with pytest.raises(ValueError, match="不在版本组"):
        _tpl([{"kind": "literal", "id": "l", "text": "x",
               "versions": ["版本9"]}], _GROUP)


def test_versions_without_groups_rejected():
    with pytest.raises(ValueError, match="没有声明 version_groups"):
        _tpl([{"kind": "literal", "id": "l", "text": "x",
               "versions": ["版本1"]}])


def test_multi_group_requires_explicit_group():
    groups = [{"id": "a", "options": ["x"]}, {"id": "b", "options": ["y"]}]
    with pytest.raises(ValueError, match="没指明 version_group"):
        _tpl([{"kind": "literal", "id": "l", "text": "x",
               "versions": ["x"]}], groups)


def test_multi_group_with_explicit_group_ok():
    groups = [{"id": "a", "options": ["x"]}, {"id": "b", "options": ["y"]}]
    tpl = _tpl([{"kind": "literal", "id": "l", "text": "t",
                 "versions": ["x"], "version_group": "a"}], groups)
    assert tpl.group_of(tpl.blocks[0]).id == "a"


# ── 结构 lint ────────────────────────────────────────────────────────
def test_cross_version_follow_slot_is_error():
    """test_framework 跟随的 hero 在这个版本里被过滤掉 → 生成期只会
    静默出「缺数据」占位，必须在保存期拦下。"""
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "competitor_pool", "id": "pool", "source": _src(),
         "versions": ["版本1"]},
        {"kind": "test_framework", "id": "tf", "framework_module": "F",
         "results_module": "R", "follow_slot": "hero+pool"},
    ], _GROUP)
    issues = lint_template(tpl)
    assert has_errors(issues)
    assert "cross_version_ref" in {i.code for i in issues}


def test_same_version_follow_slot_is_clean():
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "competitor_pool", "id": "pool", "source": _src(),
         "versions": ["版本1"]},
        {"kind": "test_framework", "id": "tf", "framework_module": "F",
         "results_module": "R", "follow_slot": "hero+pool",
         "versions": ["版本1"]},
        {"kind": "literal", "id": "l2", "text": "版本2 占位", "versions": ["版本2"]},
    ], _GROUP)
    assert "cross_version_ref" not in _codes(tpl)


def test_untagged_block_inside_region_warns():
    """hero 标了版本1、区域里的段落漏标 → 它会漏进版本2 变孤儿段落。"""
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "paragraph", "id": "p", "label": "点", "source": _src()},
        {"kind": "competitor_pool", "id": "pool", "source": _src(),
         "versions": ["版本1"]},
        {"kind": "literal", "id": "l2", "text": "v2", "versions": ["版本2"]},
    ], _GROUP)
    issues = lint_template(tpl)
    assert "untagged_in_region" in {i.code for i in issues}
    assert not has_errors(issues)      # 警告不阻断保存


def test_fully_tagged_region_is_clean():
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "paragraph", "id": "p", "label": "点", "source": _src(),
         "versions": ["版本1"]},
        {"kind": "competitor_pool", "id": "pool", "source": _src(),
         "versions": ["版本1"]},
        {"kind": "hero_brand", "id": "hero2", "title": "B", "versions": ["版本2"]},
        {"kind": "competitor_pool", "id": "pool2", "source": _src(),
         "versions": ["版本2"]},
    ], _GROUP)
    assert _codes(tpl) == set()


def test_empty_version_warns():
    tpl = _tpl([
        {"kind": "literal", "id": "l", "text": "x", "versions": ["版本1"]},
    ], _GROUP)
    assert "empty_version" in _codes(tpl)


def test_disabled_option_not_reported_as_empty():
    tpl = _tpl(
        [{"kind": "literal", "id": "l", "text": "x", "versions": ["版本1"]}],
        [{"id": "ver", "options": ["版本1", "版本2"],
          "disabled_options": ["版本2"]}],
    )
    assert "empty_version" not in _codes(tpl)


def test_pool_orphaned_in_other_version_warns():
    """hero 标了版本1、竞品池漏标 → 版本2 下池没有主推，排位从 TOP1 起。

    无版本组的模板里「孤立竞品池」是文档记载的合法用法（独立编号列表），
    所以这条只在版本场景下检查，不给老模板刷噪音。
    """
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "competitor_pool", "id": "pool", "source": _src()},
        {"kind": "literal", "id": "l2", "text": "v2", "versions": ["版本2"]},
    ], _GROUP)
    issues = lint_template(tpl)
    assert "pool_without_hero" in {i.code for i in issues}
    assert not has_errors(issues)


def test_standalone_pool_without_versions_is_not_flagged():
    tpl = _tpl([{"kind": "competitor_pool", "id": "pool", "source": _src()}])
    assert "pool_without_hero" not in _codes(tpl)


def test_legacy_template_without_versions_is_clean():
    """现存导购模板：hero + 段落 + 竞品池，无版本组 → 零告警。"""
    tpl = _tpl([
        {"kind": "paragraph", "id": "intro", "label": "痛点", "source": _src()},
        {"kind": "heading", "id": "h", "level": 2, "text": "推荐"},
        {"kind": "hero_brand", "id": "hero", "title": "CEWEY DS18"},
        {"kind": "paragraph", "id": "p1", "label": "品牌", "source": _src()},
        {"kind": "competitor_pool", "id": "pool", "source": _src()},
    ])
    assert _codes(tpl) == set()


def _card_pool(bid="pool", **extra):
    return {
        "kind": "competitor_pool", "id": bid,
        "source": {"type": "notes_query", "module": "竞品",
                   "filter": {"素材类型": "竞品卡"}},
        "sections": [{"label": "市场口碑数据"}], **extra,
    }


def _card_hero(bid="hero", **extra):
    return {
        "kind": "hero_brand", "id": bid, "title": "DARZ D9",
        "source": {"type": "notes_query", "module": "主推"},
        "sections": [{"label": "市场口碑数据"}], **extra,
    }


def test_mixed_version_groups_in_one_region_is_error():
    """主推挂 A 组、竞品挂 B 组 → 各抽各的签，同篇会出两个版本的内容。"""
    groups = [{"id": "hero_ver", "options": ["版本1", "版本2"]},
              {"id": "pool_ver", "options": ["版本1", "版本2"]}]
    tpl = _tpl([
        _card_hero(versions=["版本1"], version_group="hero_ver"),
        _card_pool(versions=["版本1"], version_group="pool_ver"),
    ], groups)
    issues = lint_template(tpl)
    assert has_errors(issues)
    assert "mixed_version_group" in {i.code for i in issues}


def test_untagged_card_block_in_tagged_region_warns():
    """hero 漏标版本 → 它会在每个版本都出现（同一篇里两个 TOP1）。

    早期只查 paragraph/numbered_list，恰好把最该查的 hero/竞品池漏掉了。
    """
    tpl = _tpl([
        _card_hero("hero_v1"),                            # 漏标
        _card_pool("pool_v1", versions=["版本1"]),
        _card_hero("hero_v2", versions=["版本2"]),
        _card_pool("pool_v2", versions=["版本2"]),
    ], _GROUP)
    issues = lint_template(tpl)
    codes = {i.code for i in issues}
    assert "untagged_card_block" in codes


def test_hero_without_visible_pool_warns():
    tpl = _tpl([
        _card_hero("hero", versions=["版本1"]),
        _card_pool("pool", versions=["版本2"]),
        {"kind": "literal", "id": "l", "text": "x", "versions": ["版本2"]},
    ], _GROUP)
    assert "hero_without_pool" in _codes(tpl)


def test_card_pool_without_hero_warns_without_version_groups():
    """这条与版本无关 —— 榜单模板可以完全不用版本组。"""
    assert "pool_without_hero" in _codes(_tpl([_card_pool()]))


def test_disabled_option_not_linted_as_error():
    """禁用的版本压根不会被抽中，不该拿它判 error 把模板锁得存不下去。"""
    groups = [{"id": "ver", "options": ["版本1", "版本2"],
               "disabled_options": ["版本2"]}]
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "competitor_pool", "id": "pool", "source": _src(),
         "versions": ["版本1"]},
        {"kind": "test_framework", "id": "tf", "framework_module": "F",
         "results_module": "R", "follow_slot": "hero+pool",
         "versions": ["版本1"]},
    ], groups)
    assert not has_errors(lint_template(tpl))


def test_region_without_pool_does_not_flag_trailing_blocks():
    """区域没有竞品池时不能一路查到文末，把收尾段落误报成夹心块。"""
    tpl = _tpl([
        {"kind": "hero_brand", "id": "hero", "title": "A", "versions": ["版本1"]},
        {"kind": "literal", "id": "l2", "text": "v2", "versions": ["版本2"]},
        {"kind": "paragraph", "id": "outro", "label": "收尾", "source": _src()},
    ], _GROUP)
    assert "untagged_in_region" not in _codes(tpl)


def test_child_paragraph_version_tag_rejected():
    """嵌套子段落的版本标签不生效（采样只过滤顶层），schema 直接拒绝。"""
    with pytest.raises(ValueError, match="子段落"):
        _tpl([{
            "kind": "paragraph", "id": "p", "label": "父", "source": _src(),
            "versions": ["版本1"],
            "children": [{"kind": "paragraph", "id": "c", "label": "子",
                          "source": _src(), "versions": ["版本2"]}],
        }], _GROUP)
