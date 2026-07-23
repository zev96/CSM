"""模板筛选的匹配语义 + 空池归因。

这两件事是一个根因的两面：用户在 UI 上照着 vault 里真实存在的取值配了筛选，
生成时却报「没有符合条件的素材」，而目录里明明躺着素材。要么是匹配语义太
窄（列表 / 数字类型对不上），要么是字段名填错了而报错不肯说错在哪。
"""
from pathlib import Path

import pytest

from csm_core.vault.scanner import explain_empty_query, match_value, scan_vault


def write(root: Path, rel: str, frontmatter: str, body: str = "正文") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")


@pytest.fixture()
def hero_vault(tmp_path: Path) -> Path:
    """复刻用户真实素材形态：素材类型全同，靠「模块」区分小节。"""
    root = tmp_path / "vault"
    for module, order in (("品牌实力", 1), ("核心参数", 3)):
        write(
            root,
            f"框架模块/空气净化器/模板二/DARZD9/{module}.md",
            "\n".join([
                "产品: 空气净化器",
                "素材类型: 产品推荐格式",
                "核心关键词:",
                "  - 模板二",
                "  - 主推位",
                f"  - {module}",
                "模板序号: 2",
                f"模块序号: {order}",
                f"模块: {module}",
                "品牌: DARZ",
            ]),
        )
    return root


# ── 匹配语义 ────────────────────────────────────────────────────────────

def test_list_frontmatter_matches_by_membership():
    # 标签集合按「含这个标签」判定 —— 严格相等的话界面上列出的取值全是死的
    assert match_value(["模板二", "主推位", "品牌实力"], "品牌实力")
    assert not match_value(["模板二", "主推位"], "品牌实力")


def test_scalar_matches_across_yaml_types():
    # YAML 把 `模板序号: 2` 读成 int，而筛选值从输入框出来永远是字符串
    assert match_value(2, "2")
    assert match_value("2", 2)
    assert not match_value(2, "3")


def test_missing_key_never_matches():
    assert not match_value(None, "品牌实力")
    assert not match_value(None, "")


def test_dict_frontmatter_is_not_coerced():
    # 嵌套结构没有合理的单值语义，别瞎猜
    assert not match_value({"a": 1}, "a")


def test_query_finds_note_by_list_tag(hero_vault: Path):
    index = scan_vault(hero_vault)
    hits = index.query(module="DARZD9", filters={"核心关键词": "品牌实力"})
    assert [n.id for n in hits] == ["品牌实力"]


def test_query_finds_note_by_int_field(hero_vault: Path):
    index = scan_vault(hero_vault)
    hits = index.query(module="DARZD9", filters={"模板序号": "2"})
    # 断言到具体是哪几篇，别只数个数 —— 放宽过头把无关笔记也捞进来照样过
    assert sorted(n.id for n in hits) == ["品牌实力", "核心参数"]


def test_date_frontmatter_matches_by_str():
    # `日期: 2026-06-26` 被 YAML 读成 date；筛选值是字符串，归一后应命中。
    # 顺带保证 explain 反查列出的取值（也走 str）是「填了真能筛出」的。
    from datetime import date
    assert match_value(date(2026, 6, 26), "2026-06-26")
    assert not match_value(date(2026, 6, 26), "2026-06-27")


def test_broadening_only_adds_never_drops():
    # 核心不变量：第一步 actual == wanted 与旧代码逐字节相同，旧命中的一篇
    # 都不会丢。这里锁住「严格相等仍恒真」这条，防止将来重构把它改坏。
    for a, w in [("x", "x"), (2, 2), (["a", "b"], ["a", "b"]), (None, None)]:
        assert match_value(a, w)


def test_mixed_type_key_enlarges_pool_intentional(tmp_path: Path):
    """同键混型（标量 + 列表）会把命中集撑大 —— 这是刻意的，钉住它。

    对抗性审查证伪了「放宽对任何本来能用的筛选零影响」这个过强的说法：某键
    在同目录里既有标量又有列表写法时，标量命中之外会补进列表命中的笔记。
    现实里被筛的字段在其目录内都是同型标量（故无触发），但语义上这是「按每
    篇自己的类型判定」的正确结果，用测试固定成预期行为而非意外。
    """
    root = tmp_path / "mixed"
    write(root, "d/scalar.md", "素材类型: 引言\n核心关键词: 吸力")
    write(root, "d/list.md", "素材类型: 引言\n核心关键词:\n  - 吸力\n  - 防缠绕")
    index = scan_vault(root)
    hits = sorted(n.id for n in index.query(module="d", filters={"核心关键词": "吸力"}))
    assert hits == ["list", "scalar"]      # 旧 strict 只会命中 scalar


# ── 空池归因 ────────────────────────────────────────────────────────────

def test_explains_wrong_field_by_pointing_at_the_right_one(hero_vault: Path):
    """用户实际踩的坑：值填对了，字段名填成了别的字段。"""
    why = explain_empty_query(
        scan_vault(hero_vault), "DARZD9", {"素材类型": "品牌实力"},
    )
    assert "2 篇" in why
    assert "产品推荐格式" in why          # 该字段的实际取值
    # 反查：值本身在哪些字段里 —— 标量的「模块」和标签列表的「核心关键词」
    # 都持有它，两个都报出来，不替用户挑
    assert "「模块」" in why
    assert "「核心关键词」" in why


def test_explains_absent_field(hero_vault: Path):
    why = explain_empty_query(
        scan_vault(hero_vault), "DARZD9", {"层级标签": "口碑之选"},
    )
    assert "没有一篇写了「层级标签」" in why
    assert "「模块」" in why              # 列出该目录真实用到的字段


def test_explains_empty_directory(hero_vault: Path):
    why = explain_empty_query(scan_vault(hero_vault), "不存在的目录", {"模块": "x"})
    assert "一篇素材都没有" in why


def test_explains_unsatisfiable_combination(hero_vault: Path):
    """每条单独都能命中，但没有素材同时满足 —— 别误导用户去改字段名。"""
    why = explain_empty_query(
        scan_vault(hero_vault), "DARZD9", {"模块": "品牌实力", "模块序号": "3"},
    )
    assert "同时满足" in why


def test_no_hint_when_value_lives_nowhere(hero_vault: Path):
    why = explain_empty_query(
        scan_vault(hero_vault), "DARZD9", {"模块": "根本没有的值"},
    )
    assert "「模块」的实际取值" in why
    assert "大概该填" not in why


def test_explains_key_without_value(hero_vault: Path):
    """编辑器里选了字段还没选值 → {字段: ""}，别报成「值填错了」。"""
    why = explain_empty_query(scan_vault(hero_vault), "DARZD9", {"模块": ""})
    assert "只选了字段、没填值" in why


def test_first_failing_filter_is_the_one_explained(hero_vault: Path):
    """多条筛选时只归因第一条真凶，不把能命中的那条也报出来。"""
    why = explain_empty_query(
        scan_vault(hero_vault), "DARZD9", {"模块": "品牌实力", "素材类型": "打错了"},
    )
    assert "「素材类型」的实际取值" in why
