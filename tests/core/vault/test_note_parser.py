from pathlib import Path
from csm_core.vault.note_parser import parse_note, ParsedNote


def test_parse_note_extracts_frontmatter(mini_vault_path: Path):
    note_path = mini_vault_path / "引言模块/吸尘器/痛点共鸣/引言-吸尘器-毛发缠绕.md"
    note = parse_note(note_path)
    assert note.frontmatter["产品"] == "吸尘器"
    assert note.frontmatter["素材类型"] == "引言"
    assert note.frontmatter["组件类型"] == "痛点共鸣"


def test_parse_note_splits_numbered_variants(mini_vault_path: Path):
    note_path = mini_vault_path / "引言模块/吸尘器/痛点共鸣/引言-吸尘器-毛发缠绕.md"
    note = parse_note(note_path)
    assert len(note.variants) == 3
    assert note.variants[0].startswith("每次吸完")
    assert note.variants[1].startswith("养宠家庭")
    assert note.variants[2].startswith("明明买的")


def test_parse_note_handles_two_variants(mini_vault_path: Path):
    note_path = mini_vault_path / "引言模块/吸尘器/痛点共鸣/引言-吸尘器-吸力衰减.md"
    note = parse_note(note_path)
    assert len(note.variants) == 2


def test_parse_note_without_variants_returns_single(mini_vault_path: Path):
    # 产品参数笔记没有 ①②③，应作为单一变体返回整文
    note_path = mini_vault_path / "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md"
    note = parse_note(note_path)
    assert len(note.variants) == 1
    assert "220AW" in note.variants[0]


def test_parsed_note_has_path_and_id(mini_vault_path: Path):
    note_path = mini_vault_path / "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md"
    note = parse_note(note_path)
    assert note.path == note_path
    assert note.id == "CEWEYDS18-产品参数"  # filename without .md
