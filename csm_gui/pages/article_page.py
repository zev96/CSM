"""Article workspace — 3-column layout: slots / markdown / controls.

Panels are placeholder QFrames; Tasks 6/7/8 populate them.
"""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QFrame


class ArticlePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")
        self.current_result = None

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.slot_panel = QFrame(self.splitter)
        self.slot_panel.setMinimumWidth(300)
        QVBoxLayout(self.slot_panel)

        self.preview_panel = QFrame(self.splitter)
        self.preview_panel.setMinimumWidth(480)
        QVBoxLayout(self.preview_panel)

        self.controls_panel = QFrame(self.splitter)
        self.controls_panel.setMinimumWidth(280)
        QVBoxLayout(self.controls_panel)

        self.splitter.addWidget(self.slot_panel)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.addWidget(self.controls_panel)
        self.splitter.setSizes([320, 720, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.current_result = None

    def load_result(self, result) -> None:
        """Populate from GenerateResult. Real wiring in Tasks 6/7."""
        self.current_result = result
