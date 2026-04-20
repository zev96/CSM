"""Article workspace — 3-column layout: slots / markdown / controls.

Controls panel is still a placeholder QFrame; Task 8 populates it.
"""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QFrame
from ..widgets.slot_list import SlotList
from ..widgets.markdown_view import MarkdownView


class ArticlePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")
        self.current_result = None
        self._template = None

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.slot_list = SlotList(self.splitter)
        self.slot_list.setMinimumWidth(300)
        # Keep attribute alias for backward compatibility with earlier tasks.
        self.slot_panel = self.slot_list

        self.markdown_view = MarkdownView(self.splitter)
        self.markdown_view.setMinimumWidth(480)
        self.preview_panel = self.markdown_view  # alias for compat

        self.controls_panel = QFrame(self.splitter)
        self.controls_panel.setMinimumWidth(280)
        QVBoxLayout(self.controls_panel)

        self.splitter.addWidget(self.slot_list)
        self.splitter.addWidget(self.markdown_view)
        self.splitter.addWidget(self.controls_panel)
        self.splitter.setSizes([320, 720, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.current_result = None
        self._template = None
        self.markdown_view.set_draft("")
        self.markdown_view.set_polished("")

    def load_result(self, template, result) -> None:
        """Populate from a Template + GenerateResult."""
        self.current_result = result
        self._template = template
        self.slot_list.load(template, result.plan)
        draft = "\n\n".join(
            "\n\n".join(p.text for p in s.picks) for s in result.plan.slots if s.picks
        )
        self.markdown_view.set_draft(draft)
        self.markdown_view.set_polished(result.final_text)
