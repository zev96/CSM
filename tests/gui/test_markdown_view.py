"""Regression tests for MarkdownView typography."""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("qfluentwidgets")

from csm_gui.widgets.markdown_view import MarkdownView


def test_set_draft_preserves_ordered_list_markers(qtbot):
    """Regression: ``_apply_typography`` previously zeroed
    ``QTextListFormat.indent``, which made Qt draw the "1." / "2."
    markers at a negative x-offset so they vanished from view.
    The list indent must stay ≥ 1 so markers remain visible.
    """
    view = MarkdownView()
    qtbot.addWidget(view)

    view.set_draft("1. CEWEY DS18\n2. 米家 3\n3. 米家 2\n")

    doc = view.draft_edit.document()
    # Walk blocks and find any list; assert its indent is non-zero.
    block = doc.firstBlock()
    found_list = False
    while block.isValid():
        tl = block.textList()
        if tl is not None:
            found_list = True
            assert tl.format().indent() >= 1, (
                "list format indent was flattened to 0; markers would clip"
            )
        block = block.next()
    assert found_list, "markdown with '1. ...' did not produce a QTextList"
