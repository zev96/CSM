from pathlib import Path
from csm_core.vault.note_parser import parse_note, ParsedNote, _strip_backlinks


def test_strip_backlinks_removes_return_and_related_block():
    body = (
        "每次吸完一屋子的头发卡在滚刷上，清理起来真的烦。\n"
        "① 刷头缠毛很多，每次都要去清理，花的时间也多。\n"
        "\n"
        "← 返回: [[引言模块总索引|返回引言模块索引]]\n"
        "相关笔记\n"
        "同类市场乱象\n"
        "  - [[乱象-吸尘器-信息过载|信息过载]] - 测评信息过多反而更迷糊\n"
    )
    out = _strip_backlinks(body)
    assert "← 返回" not in out
    assert "相关笔记" not in out
    assert "信息过载" not in out
    assert "刷头缠毛很多" in out


def test_strip_backlinks_noop_when_absent():
    body = "纯正文，无返链块。\n① 一些变体。"
    assert _strip_backlinks(body) == body


def test_parse_note_excludes_backlink_block(tmp_path: Path):
    # Synthetic note with a backlink tail — body must not leak it into variants/raw_body
    p = tmp_path / "sample.md"
    p.write_text(
        "---\n产品: 吸尘器\n组件类型: 痛点共鸣\n---\n"
        "刷头缠毛很多，每次都要去清理。\n\n"
        "← 返回: [[索引页|返回]]\n"
        "相关笔记\n  - [[其他]]\n",
        encoding="utf-8",
    )
    note = parse_note(p)
    assert "相关笔记" not in note.raw_body
    assert "← 返回" not in note.raw_body
    assert all("相关笔记" not in v for v in note.variants)


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
