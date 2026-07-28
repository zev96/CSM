from pathlib import Path

import pytest

from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.export.markdown import ensure_title, export_article


def _sample_plan() -> AssemblyPlan:
    return AssemblyPlan(
        keyword="宠物吸尘器推荐",
        template_id="daogou-changjing-renqun",
        seed=42,
        results=[BlockResult(
            block_id="intro",
            kind="paragraph",
            picks=[PickedVariant(note_id="n", variant_index=0, text="引言内容")],
        )],
    )


def test_export_writes_md(tmp_path: Path):
    """返回键是 document/format/title。

    ⚠ 早期版本还会写一份 ``{stem}.assembly.json`` 快照，返回
    ``{"markdown":…, "assembly_json":…}``；那个 sidecar 已经删了（见模块
    docstring），但这两条测试还在读 ``paths["markdown"]``，于是一直红着 ——
    盯的是一个不存在的契约，等于这个模块**没有**回归保护。
    """
    paths = export_article(
        out_dir=tmp_path,
        keyword="宠物吸尘器推荐",
        final_text="# 标题\n\n正文内容",
        plan=_sample_plan(),
    )
    assert paths["format"] == "markdown"
    assert paths["title"] == "标题"
    md_path = Path(paths["document"])
    assert md_path.exists()
    # 已有 H1 就原样落盘，不重复 prepend。
    assert md_path.read_text(encoding="utf-8") == "# 标题\n\n正文内容"


def test_export_filename_is_date_sequence(tmp_path: Path):
    """文件名是 MMDD-N，不带关键词 —— 关键词里的 / : ? 也就无从泄进文件名。"""
    paths = export_article(
        out_dir=tmp_path,
        keyword="带/特殊\\字符:的?关键词",
        final_text="x",
        plan=_sample_plan(),
    )
    name = Path(paths["document"]).name
    assert name.endswith(".md")
    for ch in ("/", "\\", ":", "?"):
        assert ch not in name


def test_export_raises_when_out_dir_missing(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        export_article(
            out_dir=nonexistent, keyword="k", final_text="t", plan=_sample_plan(),
        )


# ── 标题回填 ────────────────────────────────────────────────────────────
def test_export_prepends_missing_title(tmp_path: Path):
    """成稿正文不含标题（标题是单独字段）—— 导出必须补上。

    没补的时候导出的 .md / .docx 通篇没有标题，用户看到的是「润色把我的
    标题去掉了」；``title`` 字段还会退化成第一个章节名。
    """
    paths = export_article(
        out_dir=tmp_path, keyword="空气净化器",
        final_text="## 一、品牌分析\n\n正文", title="2026年空气净化器十大排名",
    )
    text = Path(paths["document"]).read_text(encoding="utf-8")
    assert text.startswith("# 2026年空气净化器十大排名\n\n## 一、品牌分析")
    assert paths["title"] == "2026年空气净化器十大排名"


def test_export_falls_back_to_keyword_as_title(tmp_path: Path):
    paths = export_article(out_dir=tmp_path, keyword="空气净化器", final_text="正文")
    text = Path(paths["document"]).read_text(encoding="utf-8")
    assert text.startswith("# 空气净化器\n\n正文")


def test_ensure_title_is_idempotent():
    assert ensure_title("# 甲\n\n正文", "乙") == "# 甲\n\n正文"
    # 前导空行不算数：第一行有内容的那行是不是 H1 才算数。
    assert ensure_title("\n\n# 甲\n正文", "乙") == "\n\n# 甲\n正文"
    # H2 是章节标题不是文章标题 —— 照样要补 H1。
    assert ensure_title("## 甲\n正文", "乙").startswith("# 乙\n\n## 甲")
    # 没有标题可补时不动正文（宁可没标题，也不要一个 "# " 空标题）。
    assert ensure_title("正文", "") == "正文"
    assert ensure_title("正文", "   ") == "正文"


# ── docx ────────────────────────────────────────────────────────────────
def _docx_paras(path: Path) -> list[tuple[str, str]]:
    from docx import Document
    return [(p.style.name, p.text) for p in Document(str(path)).paragraphs if p.text]


def test_docx_heading_glued_to_body_still_becomes_heading(tmp_path: Path):
    """标题和正文之间没有空行时，标题仍须是 Word 标题。

    润色链返回的正文经常是 ``## 一、品牌分析\\n正文第一句…``。旧实现按
    「整块只有一行才算标题」判定，这种块整体变成普通段落 —— Word 里看到
    的是字面的 ``##``，也就是用户说的「排版没了，变成 md 代码格式」。
    """
    paths = export_article(
        out_dir=tmp_path, keyword="k", fmt="docx", title="标题",
        final_text="## 一、品牌分析\n正文第一句\n正文第二句\n\n### TOP1. 甲\n**小节**：内容",
    )
    paras = _docx_paras(Path(paths["document"]))
    style_of = {text: style for style, text in paras}
    assert style_of["一、品牌分析"].startswith("Heading")
    assert style_of["TOP1. 甲"].startswith("Heading")
    # 正文仍然合成一个段落（软换行），且不带字面 ## / **
    body = [t for s, t in paras if not s.startswith("Heading")]
    assert any("正文第一句" in t and "正文第二句" in t for t in body)
    assert not any("#" in t for t in body)
    assert not any("**" in t for t in body)


def test_docx_single_line_heading_block_unchanged(tmp_path: Path):
    """零回归：标题独占一块时行为与以前逐字节一致。"""
    paths = export_article(
        out_dir=tmp_path, keyword="k", fmt="docx", title="标题",
        final_text="## 章节\n\n正文",
    )
    paras = _docx_paras(Path(paths["document"]))
    assert ("Heading 2", "章节") in paras
    assert any(s == "Normal" and t == "正文" for s, t in paras)


def test_ensure_title_squashes_multiline_title():
    """H1 是单行结构，多行标题拼进去第二行就变成正文了。"""
    assert ensure_title("正文", "  多行\n标题  ") == "# 多行 标题\n\n正文"


def test_ensure_title_accepts_tab_after_hash():
    """判据与 _heading_level 同款：`#\t标题` 是 H1，不该被再补一个。"""
    assert ensure_title("#\t制表符标题\n正文", "别的") == "#\t制表符标题\n正文"
