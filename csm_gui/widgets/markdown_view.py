"""Two-tab markdown preview: draft + polished."""
from __future__ import annotations
from PyQt6.QtGui import QTextFrameFormat
from PyQt6.QtWidgets import QVBoxLayout, QStackedWidget, QFrame
from qfluentwidgets import Pivot, TextEdit, CardWidget


# Strip the chrome that ``QTextEdit`` paints by default so the widget blends
# into the surrounding Fluent card: no widget frame, no per-block frame
# border (Qt 6's setMarkdown adds a root QTextFrame with a border), and a
# transparent viewport so the CardWidget colour shows through.
_MD_STYLESHEET = """
TextEdit {
    border: none;
    background: transparent;
}
"""


def _strip_block_borders(edit) -> None:
    """Remove the root QTextFrame border that Qt draws around each block
    after ``setMarkdown`` / ``setHtml``. This is the source of the thin
    rectangular outline the user sees around every paragraph.
    """
    doc = edit.document()
    fmt = QTextFrameFormat()
    fmt.setBorder(0)
    fmt.setPadding(0)
    fmt.setMargin(0)
    doc.rootFrame().setFrameFormat(fmt)


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

        for edit in (self.draft_edit, self.polished_edit):
            edit.setFrameShape(QFrame.Shape.NoFrame)
            edit.setStyleSheet(_MD_STYLESHEET)
            _strip_block_borders(edit)

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
        _strip_block_borders(self.draft_edit)

    def get_draft_text(self) -> str:
        return self.draft_edit.toMarkdown()

    def set_polished(self, md: str):
        # Only auto-switch to the 成文 tab when there's actual polished
        # content to show — otherwise a fresh generate that preloads an
        # empty polished string would leave the user on a blank tab.
        self.polished_edit.setMarkdown(md)
        _strip_block_borders(self.polished_edit)
        if md.strip():
            self._pivot.setCurrentItem("polished")
        else:
            self._pivot.setCurrentItem("draft")
