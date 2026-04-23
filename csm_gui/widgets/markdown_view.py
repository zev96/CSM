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
        # AND stays editable — ``QTextEdit.toMarkdown()`` converts the
        # current rich-text document back to markdown for the polish stage,
        # so user edits round-trip cleanly through set_draft -> edit ->
        # get_draft_text.
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
        # Render markdown for display; Qt keeps an internal rich-text
        # document that's editable, and ``toMarkdown`` reproduces the
        # markdown source on demand.
        self.draft_edit.setMarkdown(md)

    def get_draft_text(self) -> str:
        return self.draft_edit.toMarkdown()

    def set_polished(self, md: str):
        # Only auto-switch to the 成文 tab when there's actual polished
        # content to show — otherwise a fresh generate that preloads an
        # empty polished string would leave the user on a blank tab.
        self.polished_edit.setMarkdown(md)
        if md.strip():
            self._pivot.setCurrentItem("polished")
        else:
            self._pivot.setCurrentItem("draft")
