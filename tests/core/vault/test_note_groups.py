"""「一篇笔记 = 一个小节」的目录归纳（主推卡从目录识别的内核）。"""
from pathlib import Path

from csm_core.vault.note_groups import (
    field_candidates, group_notes_by_field, order_field_for,
)
from csm_core.vault.scanner import scan_vault


def _note(vault: Path, name: str, fm: dict, body: str = "① 正文") -> None:
    p = vault / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines.extend(f"  - {x}" for x in v)
        else:
            lines.append(f"{k}: {v}")
    lines += ["---", body]
    p.write_text("\n".join(lines), encoding="utf-8")


def _vault(tmp_path: Path, notes: list[tuple[str, dict]], **kw) -> list:
    for name, fm in notes:
        _note(tmp_path, name, fm, **kw)
    return scan_vault(tmp_path).notes


# ── 字段推断 ────────────────────────────────────────────────────────────
def test_picks_field_that_splits_one_note_per_value(tmp_path):
    notes = _vault(tmp_path, [
        ("a", {"品牌": "DARZ", "模块": "品牌实力", "产品": "空气净化器"}),
        ("b", {"品牌": "DARZ", "模块": "核心技术", "产品": "空气净化器"}),
        ("c", {"品牌": "DARZ", "模块": "核心参数", "产品": "空气净化器"}),
    ])
    assert field_candidates(notes)[0] == "模块"


def test_uniform_fields_are_not_candidates(tmp_path):
    """全同的字段（品牌/产品）分不开笔记，压根不该进候选。"""
    notes = _vault(tmp_path, [
        ("a", {"品牌": "DARZ", "模块": "甲"}),
        ("b", {"品牌": "DARZ", "模块": "乙"}),
    ])
    assert "品牌" not in field_candidates(notes)


def test_prefers_named_field_over_numeric_sibling(tmp_path):
    """`模块` 和 `模块序号` 都能一篇一值 —— 小节名该是名字不是「0/1/2」。"""
    notes = _vault(tmp_path, [
        ("a", {"模块": "品牌实力", "模块序号": 1}),
        ("b", {"模块": "核心技术", "模块序号": 2}),
    ])
    cands = field_candidates(notes)
    assert cands[0] == "模块"
    assert "模块序号" in cands


def test_list_fields_cannot_group(tmp_path):
    """列表字段一篇会落进多个组，当不了「一篇 = 一节」的分组键。"""
    notes = _vault(tmp_path, [
        ("a", {"核心关键词": ["模板二", "主推位", "品牌实力"], "模块": "品牌实力"}),
        ("b", {"核心关键词": ["模板二", "主推位", "核心技术"], "模块": "核心技术"}),
    ])
    assert "核心关键词" not in field_candidates(notes)


def test_candidate_order_is_deterministic(tmp_path):
    """识别结果要能复现 —— 同分时按字段名，不看 dict 遍历顺序。"""
    notes = _vault(tmp_path, [
        ("a", {"乙": "1", "甲": "x"}),
        ("b", {"乙": "2", "甲": "y"}),
    ])
    assert field_candidates(notes) == field_candidates(list(reversed(notes)))


def test_no_candidates_when_nothing_discriminates(tmp_path):
    notes = _vault(tmp_path, [
        ("a", {"品牌": "DARZ"}),
        ("b", {"品牌": "DARZ"}),
    ])
    assert field_candidates(notes) == []


def test_empty_notes_no_crash():
    assert field_candidates([]) == []


# ── 排序字段 ────────────────────────────────────────────────────────────
def test_order_field_prefers_same_prefix(tmp_path):
    notes = _vault(tmp_path, [
        ("a", {"模块": "甲", "模块序号": 2, "另一个编号": 9}),
        ("b", {"模块": "乙", "模块序号": 1, "另一个编号": 8}),
    ])
    assert order_field_for(notes, "模块") == "模块序号"


def test_order_field_none_when_no_numeric_key(tmp_path):
    notes = _vault(tmp_path, [("a", {"模块": "甲"}), ("b", {"模块": "乙"})])
    assert order_field_for(notes, "模块") is None


# ── 归组 ────────────────────────────────────────────────────────────────
def test_group_sorts_by_order_field_not_filename(tmp_path):
    """小节先后直接决定成文排版，按文件名排就乱了。"""
    notes = _vault(tmp_path, [
        ("zzz", {"模块": "第一节", "模块序号": 1}),
        ("aaa", {"模块": "第二节", "模块序号": 2}),
    ])
    got = group_notes_by_field(notes, "模块", order_field=order_field_for(notes, "模块"))
    assert [g.value for g in got] == ["第一节", "第二节"]


def test_group_without_order_field_uses_scan_order(tmp_path):
    notes = _vault(tmp_path, [("a", {"模块": "甲"}), ("b", {"模块": "乙"})])
    got = group_notes_by_field(notes, "模块")
    assert [g.value for g in got] == [n.frontmatter["模块"] for n in notes]


def test_group_merges_same_value_and_counts_bodies(tmp_path):
    _note(tmp_path, "a", {"模块": "甲", "模块序号": 1}, body="① 有正文")
    _note(tmp_path, "b", {"模块": "甲", "模块序号": 2}, body="")
    _note(tmp_path, "c", {"模块": "乙", "模块序号": 3}, body="① 有正文")
    notes = scan_vault(tmp_path).notes
    got = {g.value: g for g in group_notes_by_field(notes, "模块", order_field="模块序号")}
    assert got["甲"].note_count == 2
    assert got["甲"].with_body == 1
    # 同取值多篇时按**最小**序号定位，整组不会被落在后面那篇拖到队尾
    assert got["甲"].order < got["乙"].order


def test_group_skips_notes_missing_the_field(tmp_path):
    _note(tmp_path, "a", {"模块": "甲"})
    _note(tmp_path, "b", {"品牌": "DARZ"})
    got = group_notes_by_field(scan_vault(tmp_path).notes, "模块")
    assert [g.value for g in got] == ["甲"]


def test_order_field_is_deterministic_across_processes(tmp_path):
    """同前缀的两个候选（模块序号 / 模块排序）不能靠 set 遍历顺序定胜负。

    直接 for 一个 set，字符串哈希随机化会让两者跨进程各赢一次，而它们给出
    的小节顺序可能正好相反 —— 「同一个目录识别两次结果不同」。
    """
    notes = _vault(tmp_path, [
        ("a", {"模块": "甲", "模块序号": 1, "模块排序": 3}),
        ("b", {"模块": "乙", "模块序号": 2, "模块排序": 2}),
        ("c", {"模块": "丙", "模块序号": 3, "模块排序": 1}),
    ])
    picked = order_field_for(notes, "模块")
    assert picked is not None
    # 同一份输入换个顺序、重复调用，结论必须一样
    for _ in range(5):
        assert order_field_for(list(reversed(notes)), "模块") == picked


def test_order_field_tolerates_duplicate_numbers(tmp_path):
    """手填序号撞车不该整个退回文件名序（=字母序），那才是看得见的排版事故。"""
    _note(tmp_path, "zz", {"模块": "第一节", "模块序号": 1})
    _note(tmp_path, "yy", {"模块": "并列", "模块序号": 1})
    _note(tmp_path, "aa", {"模块": "第三节", "模块序号": 3})
    notes = scan_vault(tmp_path).notes
    assert order_field_for(notes, "模块") == "模块序号"
    got = group_notes_by_field(notes, "模块", order_field="模块序号")
    assert [g.value for g in got][-1] == "第三节"
