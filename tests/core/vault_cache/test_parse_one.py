from pathlib import Path

from csm_core.vault.scanner import parse_one, scan_vault


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


GOOD = "---\n素材类型: 科普\n---\n\n正文①\n"
NO_FM = "没有 frontmatter 的裸文本\n"


def test_parse_one_good(tmp_path):
    note, warning = parse_one(_write(tmp_path / "a.md", GOOD))
    assert warning is None
    assert note is not None and note.id == "a"
    assert note.frontmatter.get("素材类型") == "科普"


def test_parse_one_missing_frontmatter(tmp_path):
    note, warning = parse_one(_write(tmp_path / "b.md", NO_FM))
    assert note is None
    assert warning == "b.md: 缺少 frontmatter"


def test_parse_one_broken_yaml(tmp_path):
    note, warning = parse_one(_write(tmp_path / "c.md", "---\n: [broken\n---\nx"))
    assert note is None
    assert warning is not None and warning.startswith("c.md: 解析失败")


def test_scan_vault_unchanged(tmp_path):
    _write(tmp_path / "a.md", GOOD)
    _write(tmp_path / "b.md", NO_FM)
    idx = scan_vault(tmp_path)
    assert [n.id for n in idx.notes] == ["a"]
    assert idx.warnings == ["b.md: 缺少 frontmatter"]
    assert idx.by_id["a"].id == "a"
