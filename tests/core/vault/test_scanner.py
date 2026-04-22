from pathlib import Path
from csm_core.vault.scanner import scan_vault, VaultIndex


def test_scan_vault_returns_index(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    assert isinstance(index, VaultIndex)
    assert len(index.notes) == 31


def test_index_groups_by_module(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    intro_notes = index.by_module("引言模块")
    assert len(intro_notes) == 6
    keypoint_notes = index.by_module("科普模块/挑选攻略")
    assert len(keypoint_notes) == 6


def test_index_filter_by_frontmatter(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    matches = index.query(module="引言模块", filters={"组件类型": "痛点共鸣"})
    assert len(matches) == 2
    for note in matches:
        assert note.frontmatter["组件类型"] == "痛点共鸣"


def test_index_filter_returns_empty_when_no_match(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    matches = index.query(module="引言模块", filters={"组件类型": "不存在"})
    assert matches == []


def test_index_lookup_by_id(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    note = index.get("CEWEYDS18-产品参数")
    assert note is not None
    assert note.frontmatter["品牌"] == "CEWEY"


def test_scan_records_warnings_for_missing_frontmatter(tmp_path: Path):
    bad = tmp_path / "营销资料库" / "bad.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("no frontmatter here", encoding="utf-8")
    index = scan_vault(tmp_path / "营销资料库")
    assert len(index.warnings) >= 1
    assert "bad.md" in index.warnings[0]
