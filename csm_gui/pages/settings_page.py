"""Settings — filled in Task 2."""
from __future__ import annotations
from qfluentwidgets import SubtitleLabel
from PyQt6.QtWidgets import QWidget, QVBoxLayout


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        layout = QVBoxLayout(self)
        layout.addWidget(SubtitleLabel("设置"))
