from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.assembler.sampler import sample_block
from csm_core.template.schema import (
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    NotesQuerySource,
)


def _write(vault: Path, rel: str, frontmatter: dict, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")


def test_sample_heading_returns_text_block_result(tmp_path):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = HeadingBlock(id="h1", level=2, index="一", text="{keyword}怎么选")
    br = sample_block(blk, idx, reg, seed=0, user_config={})
    assert br.kind == "heading"
    assert br.text == "{keyword}怎么选"
    assert br.meta == {"level": 2, "index": "一"}
    assert br.picks == []


def test_sample_literal(tmp_path):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    br = sample_block(LiteralBlock(id="l1", text="完。"), idx, reg, seed=0, user_config={})
    assert br.kind == "literal" and br.text == "完。"


def test_sample_hero_brand(tmp_path):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    hb = HeroBrandBlock(id="h", title="CEWEY DS18", number_style="1.")
    br = sample_block(hb, idx, reg, seed=0, user_config={})
    assert br.kind == "hero_brand"
    assert br.text == "CEWEY DS18"
    assert br.meta["number_style"] == "1."
    assert br.meta["reason_label"] == "推荐理由："


def test_sample_paragraph_from_vault(tmp_path):
    _write(tmp_path, "A/a.md", {"产品": "吸尘器"}, "段落A文本")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = ParagraphBlock(
        id="s1", label="A",
        source=NotesQuerySource(module="A"),
        pick_notes=1, pick_variants_per_note=1,
    )
    br = sample_block(blk, idx, reg, seed=42, user_config={})
    assert br.kind == "paragraph"
    assert len(br.picks) == 1
    assert "段落A文本" in br.picks[0].text


def test_sample_numbered_list_picks_N(tmp_path):
    for i in range(5):
        _write(tmp_path, f"L/{i}.md", {"产品": "吸尘器"}, f"条目{i}")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = NumberedListBlock(
        id="n1", label="L", source=NotesQuerySource(module="L"),
        pick_notes=3, number_style="1.",
    )
    br = sample_block(blk, idx, reg, seed=1, user_config={})
    assert br.kind == "numbered_list"
    assert len(br.picks) == 3
    assert br.meta["number_style"] == "1."


def test_sample_competitor_pool_extracts_title_from_frontmatter(tmp_path):
    body = (
        "① 第一版推荐理由文字…\n\n"
        "② 第二版推荐理由文字…\n\n"
        "③ 第三版推荐理由文字…\n"
    )
    _write(tmp_path, "竞品/戴森V8.md", {"型号": "戴森V8", "产品": "吸尘器"}, body)
    _write(tmp_path, "竞品/小狗T12.md", {"型号": "小狗T12", "产品": "吸尘器"}, body)
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = CompetitorPoolBlock(
        id="cp", source=NotesQuerySource(module="竞品"),
        pick_notes={"random_between": [2, 2]},
    )
    br = sample_block(blk, idx, reg, seed=3, user_config={})
    assert br.kind == "competitor_pool"
    assert len(br.picks) == 2
    for p in br.picks:
        assert p.meta.get("title") in ("戴森V8", "小狗T12")
        assert "推荐理由文字" in p.text


def test_competitor_pool_no_type_key_falls_back_to_stem(tmp_path):
    _write(tmp_path, "竞品/无型号的竞品.md", {"产品": "吸尘器"}, "整篇作为单一理由。")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = CompetitorPoolBlock(
        id="cp", source=NotesQuerySource(module="竞品"),
        pick_notes=1,
    )
    br = sample_block(blk, idx, reg, seed=0, user_config={})
    assert br.picks[0].meta["title"] == "无型号的竞品"


def test_competitor_pool_stem_strips_leading_jingpin_prefix(tmp_path):
    # Vault convention: note stems like "竞品-米家3基站版" include the category
    # prefix. When there's no explicit 型号 frontmatter the renderer should
    # show the title without the "竞品-" prefix.
    _write(tmp_path, "竞品/竞品-米家3基站版.md", {"产品": "吸尘器"}, "整篇理由。")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = CompetitorPoolBlock(
        id="cp", source=NotesQuerySource(module="竞品"),
        pick_notes=1,
    )
    br = sample_block(blk, idx, reg, seed=0, user_config={})
    assert br.picks[0].meta["title"] == "米家3基站版"
