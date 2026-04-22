"""Two-tab markdown preview: draft + polished."""
from __future__ import annotations
from PyQt6.QtWidgets import QVBoxLayout, QStackedWidget
from qfluentwidgets import Pivot, TextEdit, CardWidget


class MarkdownView(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedWidget(self)
        self._pivot = Pivot(self)

        # Draft tab is user-editable: the two-phase flow lets the user tweak
        # the assembled draft before it's handed to the LLM for polishing.
        self.draft_edit = TextEdit(self)
        self.draft_edit.setReadOnly(False)
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
        # Use setPlainText (not setMarkdown) so what the user sees and edits
        # is the exact draft text — including the explicit module headers —
        # and the same bytes flow through to ``get_draft_text`` -> polish.
        self.draft_edit.setPlainText(md)

    def get_draft_text(self) -> str:
        return self.draft_edit.toPlainText()

    def set_polished(self, md: str):
        self.polished_edit.setMarkdown(md)
        self._pivot.setCurrentItem("polished")
