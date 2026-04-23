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


def test_strip_backlinks_removes_bold_label_style():
    # Real vault notes use **返回上层**: / **返回主页**: instead of ← 返回
    body = (
        "① 很多无线吸尘器尘杯小到没吸几下就满了。\n"
        "\n"
        "**返回上层**: [[引言模块总索引|返回引言模块索引]]\n"
        "**返回主页**: 关联数据库\n"
    )
    out = _strip_backlinks(body)
    assert "返回上层" not in out
    assert "返回主页" not in out
    assert "关联数据库" not in out
    assert "引言模块总索引" not in out
    assert "吸尘器尘杯小" in out


def test_strip_backlinks_removes_naked_label_style():
    body = (
        "正文段落。\n"
        "返回上层: [[索引]]\n"
        "返回主页: 主页\n"
    )
    out = _strip_backlinks(body)
    assert "返回上层" not in out
    assert "返回主页" not in out
    assert out.strip() == "正文段落。"


def test_strip_backlinks_removes_inline_related_notes():
    # Vault style where 相关笔记 is followed by inline wiki-link tail
    # instead of being a standalone header. Previous regex anchored
    # on end-of-line so the whole line leaked into the draft.
    body = (
        "① 实测持续输出 220AW 吸力。\n"
        "\n"
        "相关笔记: [[友望大橘-产品参数|产品参数]] | "
        "[[友望大橘-测试结果|实测结果]]\n"
    )
    out = _strip_backlinks(body)
    assert "相关笔记" not in out
    assert "友望大橘-产品参数" not in out
    assert "实测结果" not in out
    assert "220AW" in out


def test_strip_backlinks_removes_bold_related_notes():
    body = (
        "① 正文。\n"
        "**相关笔记**: [[友望大橘-产品参数|产品参数]]\n"
    )
    out = _strip_backlinks(body)
    assert "相关笔记" not in out
    assert "友望大橘" not in out
    assert out.strip() == "① 正文。"


def test_strip_backlinks_noop_when_absent():
    body = "纯正文，无返链块。\n① 一些变体。"
    assert _strip_backlinks(body) == body


def test_parse_note_handles_utf8_bom(tmp_path: Path):
    # Notes saved by some editors (e.g. Typora on Windows) start with a
    # UTF-8 BOM. The parser must strip it so frontmatter is still recognised.
    p = tmp_path / "bom.md"
    p.write_bytes(
        "\ufeff---\n产品: 吸尘器\n素材类型: 竞品推荐理由\n---\n① 正文\n".encode("utf-8")
    )
    note = parse_note(p)
    assert note.frontmatter.get("产品") == "吸尘器"
    assert note.frontmatter.get("素材类型") == "竞品推荐理由"
    assert note.variants and "正文" in note.variants[0]


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


def test_parse_note_strips_stray_hr_between_variants(tmp_path: Path):
    # Real vault notes sometimes place a ``---`` horizontal rule between the
    # last variant and the backlink tail. It must not leak into variant text.
    p = tmp_path / "hr.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 竞品推荐理由\n---\n"
        "① 第一条卖点。\n"
        "② 第二条卖点。\n"
        "\n---\n"
        "**返回上层**: [[索引]]\n",
        encoding="utf-8",
    )
    note = parse_note(p)
    assert len(note.variants) == 2
    assert all("---" not in v for v in note.variants)


def test_parse_note_strips_markdown_headings_in_variant(tmp_path: Path):
    # ``###`` subheadings inside a variant body should be demoted to plain text
    # (marker stripped, heading text kept) so drafts stay as flat prose.
    p = tmp_path / "hd.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 竞品推荐理由\n---\n"
        "① 前置说明。\n### 产品优势\n这里是优势描述。\n",
        encoding="utf-8",
    )
    note = parse_note(p)
    assert len(note.variants) == 1
    v = note.variants[0]
    assert "###" not in v
    assert "产品优势" in v
    assert "优势描述" in v


def test_parse_note_splits_heading_wrapped_variant_markers(tmp_path: Path):
    # Real 挑选攻略 notes wrap each variant marker in an ATX heading, e.g.
    # ``### ① 噪音控制水平``. Prior to this test the splitter only looked at
    # the raw character after ``lstrip`` — ``#`` — and collapsed every
    # numbered section into a single variant, which then leaked through as
    # one multi-section pick regardless of ``pick_variants_per_note=1``.
    p = tmp_path / "hdmark.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n---\n"
        "### ① 噪音控制水平\n"
        "噪音基本上吸尘器很难避免的。\n"
        "\n"
        "### ② 选择噪音低能接受的\n"
        "噪音是吸尘器使用体验的重要参数。\n",
        encoding="utf-8",
    )
    note = parse_note(p)
    assert len(note.variants) == 2
    assert note.variants[0].startswith("噪音控制水平")
    assert note.variants[1].startswith("选择噪音低能接受的")
    # Crucially, neither variant leaks content from the other.
    assert "选择噪音低能接受的" not in note.variants[0]
    assert "噪音控制水平" not in note.variants[1]


def test_parse_note_splits_variants_past_nine(tmp_path: Path):
    """Regression: notes with ⑩+ must split correctly.

    The parser's original regex only covered ①–⑨, so variant 9 absorbed
    ⑩⑪⑫… into its body — producing a multi-section pick instead of the
    intended single-variant text.
    """
    p = tmp_path / "longlist.md"
    body = "".join(f"{chr(0x245F + i)} 第 {i} 条卖点。\n" for i in range(1, 13))
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 竞品推荐理由\n---\n" + body,
        encoding="utf-8",
    )
    note = parse_note(p)
    assert len(note.variants) == 12
    # Crucially, variant 9 must not leak ⑩⑪⑫ content into it.
    assert "⑩" not in note.variants[8]
    assert "⑪" not in note.variants[8]
    assert "第 9 条" in note.variants[8]
    assert "第 10 条" in note.variants[9]
    assert "第 12 条" in note.variants[11]
    # None of the markers should survive on their owning variant either.
    for v in note.variants:
        assert not v.lstrip().startswith(tuple(chr(c) for c in range(0x2460, 0x2474)))


def test_parse_note_strips_indented_variant_markers(tmp_path: Path):
    # Variant markers can appear indented in some notes; the leading marker
    # must still be stripped so ``② ...`` doesn't leak into the draft.
    p = tmp_path / "idt.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 竞品推荐理由\n---\n"
        "  ① 第一条。\n"
        "  ② 第二条。\n",
        encoding="utf-8",
    )
    note = parse_note(p)
    assert len(note.variants) == 2
    assert all(not v.lstrip().startswith(("①", "②", "③")) for v in note.variants)


def test_parse_note_strips_markdown_bold(tmp_path: Path):
    # ``**强调**`` inline bold markers must be peeled off so variants render as
    # plain prose in the assembled draft.
    p = tmp_path / "bold.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 竞品推荐理由\n---\n"
        "① **我们选购时一定要看**尘杯容量大小。\n",
        encoding="utf-8",
    )
    note = parse_note(p)
    assert "**" not in note.variants[0]
    assert "我们选购时一定要看" in note.variants[0]
    assert "尘杯容量大小" in note.variants[0]


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
