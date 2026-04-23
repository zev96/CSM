"""Two-tab markdown preview: draft + polished."""
from __future__ import annotations
from PyQt6.QtWidgets import QVBoxLayout, QStackedWidget
from qfluentwidgets import Pivot, TextEdit, CardWidget


class MarkdownView(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedWidget(self)
        self._pivot = Pivot(self)

        # Draft tab renders markdown for display (H1/H2 styled, lists, etc.)
        # so structural symbols like ``##`` aren't shown verbatim. The raw
        # source is preserved in ``_draft_source`` and returned by
        # ``get_draft_text()`` so the polish stage still sees the exact
        # markdown bytes. The widget is read-only because ``toPlainText()``
        # on a setMarkdown'd TextEdit strips the ``##`` tokens — in-place
        # editing wouldn't round-trip cleanly. Users can re-roll or
        # regenerate instead.
        self.draft_edit = TextEdit(self)
        self.draft_edit.setReadOnly(True)
        self._draft_source = ""
        self.polished_edit = TextEdit(self)
        self.polished_edit.setReadOnly(True)

        self._stack.addWidget(self.draft_edit)
        self._stack.addWidget(self.polished_edit)

        self._pivot.addItem(routeKey="draft", text="初稿")
        self._pivot.addItem(routeKey="polished", text="成文")
        self._pivot.currentItemChanged.connect(self._on_tab)
        self._pivot.setCurrentItem("draft")

        root = QVBoxLayout(self)
        root.addWidget(self._pivot)
        root.addWidget(self._stack, 1)

    def _on_tab(self, key: str):
        self._stack.setCurrentIndex(0 if key == "draft" else 1)

    def set_draft(self, md: str):
        # Render markdown for display but stash the original source so the
        # polish stage sees the exact bytes (with ``##`` intact).
        self._draft_source = md
        self.draft_edit.setMarkdown(md)

    def get_draft_text(self) -> str:
        return self._draft_source

    def set_polished(self, md: str):
        self.polished_edit.setMarkdown(md)
        self._pivot.setCurrentItem("polished")
