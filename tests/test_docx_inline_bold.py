"""Test docx export inline-bold (``**text**``) handling."""
from __future__ import annotations
import tempfile
from pathlib import Path

import pytest

# python-docx is an optional dep — skip the suite if it's not installed
# (e.g. on a developer box that only does .md export).
docx = pytest.importorskip("docx")

from csm_core.export.markdown import (
    _BOLD_RE, _strip_bold_markers, _write_docx,
)


class TestStripBoldMarkers:
    def test_full_wrap(self):
        assert _strip_bold_markers("**品牌推荐**") == "品牌推荐"

    def test_partial(self):
        assert _strip_bold_markers("一、**推荐**清单") == "一、推荐清单"

    def test_no_markers(self):
        assert _strip_bold_markers("plain text") == "plain text"

    def test_multiple(self):
        assert _strip_bold_markers("**A** + **B**") == "A + B"

    def test_unmatched_kept(self):
        # 只有左边的 **，没有匹配，原样保留
        assert _strip_bold_markers("**lonely") == "**lonely"


class TestBoldRegex:
    def test_finds_inner_text(self):
        matches = [m.group(1) for m in _BOLD_RE.finditer(
            "前缀 **加粗内容** 后缀"
        )]
        assert matches == ["加粗内容"]

    def test_does_not_cross_newlines(self):
        # 故意用三引号字符串保留实际换行
        matches = list(_BOLD_RE.finditer("**第一行\n第二行**"))
        assert matches == []


class TestDocxInlineBold:
    def _docx_paragraphs(self, tmp_path: Path, source: str) -> list:
        path = tmp_path / "out.docx"
        _write_docx(path, source)
        from docx import Document
        return Document(str(path)).paragraphs

    def test_bold_paragraph_renders_as_bold_run(self, tmp_path: Path):
        text = "**1. CEWEY DS18 家用吸尘器**"
        ps = self._docx_paragraphs(tmp_path, text)
        assert len(ps) == 1
        runs = ps[0].runs
        assert len(runs) == 1
        assert runs[0].bold is True
        assert runs[0].text == "1. CEWEY DS18 家用吸尘器"
        # No literal asterisks
        assert "**" not in runs[0].text

    def test_inline_bold_in_prose(self, tmp_path: Path):
        text = "选购 **CEWEY DS18** 时要看噪音控制。"
        ps = self._docx_paragraphs(tmp_path, text)
        runs = ps[0].runs
        # 三段：前缀 + 加粗 + 后缀
        assert [r.text for r in runs] == [
            "选购 ", "CEWEY DS18", " 时要看噪音控制。",
        ]
        assert [bool(r.bold) for r in runs] == [False, True, False]

    def test_heading_strips_bold_markers(self, tmp_path: Path):
        text = "## **品牌推荐**"
        ps = self._docx_paragraphs(tmp_path, text)
        assert ps[0].style.name == "Heading 2"
        # 标题文本里不应出现星号
        runs_text = "".join(r.text for r in ps[0].runs)
        assert runs_text == "品牌推荐"
        assert "**" not in runs_text

    def test_plain_paragraph_no_bold(self, tmp_path: Path):
        text = "普通的一段话。"
        ps = self._docx_paragraphs(tmp_path, text)
        assert all(not r.bold for r in ps[0].runs)
