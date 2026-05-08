"""Tray right-click menu.

Six actions, each fires its own pyqtSignal so the parent can route
them without inspecting QAction identity.
"""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QWidget


class TrayMenu(QMenu):
    show_requested = pyqtSignal()
    new_article_requested = pyqtSignal()
    new_template_requested = pyqtSignal()
    new_skill_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._add("显示主界面", self.show_requested)
        self._add("新建文章", self.new_article_requested)
        self._add("新建模板", self.new_template_requested)
        self._add("新建 Skill", self.new_skill_requested)
        self._add("设置", self.settings_requested)
        self.addSeparator()
        self._add("退出 CSM", self.quit_requested)

    def _add(self, label: str, signal) -> QAction:
        act = QAction(label, self)
        act.triggered.connect(signal.emit)
        self.addAction(act)
        return act
