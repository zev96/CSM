"""Article workspace — filled in Task 5+."""
from __future__ import annotations
from qfluentwidgets import SubtitleLabel
from PyQt6.QtWidgets import QWidget, QVBoxLayout


class ArticlePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")
        layout = QVBoxLayout(self)
        layout.addWidget(SubtitleLabel("文章工作区"))
