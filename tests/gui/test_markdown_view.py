"""Regression tests for MarkdownView typography."""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("qfluentwidgets")

from csm_gui.widgets.markdown_view import (
    MarkdownView, _escape_ordered_list_prefixes,
)


def test_escape_ordered_list_prefixes_escapes_line_start():
    md = "1. CEWEY DS18\n2. 米家 3\n\nsome inline 3. text should stay\n"
    out = _escape_ordered_list_prefixes(md)
    assert "1\\. CEWEY DS18" in out
    assert "2\\. 米家 3" in out
    # inline "3." mid-line must NOT be escaped
    assert "inline 3. text" in out


def test_set_draft_numbered_prefixes_render_as_paragraphs(qtbot):
    """Regression: ``compose_draft`` emits "1. CEWEY ..." as a literal
    prefix, not as a markdown ordered list. ``setMarkdown`` used to
    re-parse those into ``QTextList`` items whose markers sat at a
    fixed indent that wouldn't align with surrounding paragraph text.
    After the escape, the lines must render as plain paragraphs —
    no ``QTextList`` should be created for renderer-emitted indices.
    """
    view = MarkdownView()
    qtbot.addWidget(view)

    view.set_draft("1. CEWEY DS18\n2. 米家 3\n3. 米家 2\n")

    doc = view.draft_edit.document()
    block = doc.firstBlock()
    while block.isValid():
        assert block.textList() is None, (
            "numbered-prefix line materialised as QTextList; "
            "escape was not applied before setMarkdown"
        )
        block = block.next()
