"""Home page — keyword + template form. Filled in Task 3."""
from __future__ import annotations
from qfluentwidgets import SubtitleLabel
from PyQt6.QtWidgets import QWidget, QVBoxLayout


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        layout = QVBoxLayout(self)
        layout.addWidget(SubtitleLabel("首页"))
