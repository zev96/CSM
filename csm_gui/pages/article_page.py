"""Article workspace — 3-column layout: slots / markdown / controls.

Preview and controls panels are still placeholder QFrames; Tasks 7/8 populate them.
"""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QFrame
from ..widgets.slot_list import SlotList


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

        self.preview_panel = QFrame(self.splitter)
        self.preview_panel.setMinimumWidth(480)
        QVBoxLayout(self.preview_panel)

        self.controls_panel = QFrame(self.splitter)
        self.controls_panel.setMinimumWidth(280)
        QVBoxLayout(self.controls_panel)

        self.splitter.addWidget(self.slot_list)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.addWidget(self.controls_panel)
        self.splitter.setSizes([320, 720, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.current_result = None
        self._template = None

    def load_result(self, template, result) -> None:
        """Populate from a Template + GenerateResult."""
        self.current_result = result
        self._template = template
        self.slot_list.load(template, result.plan)
