"""UpdateDialog — modal: 'Found new version' with changelog + buttons."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton,
)
from qfluentwidgets import StrongBodyLabel, BodyLabel, PrimaryPushButton

from csm_core.updater_client.manifest import UpdateInfo


class UpdateDialog(QDialog):
    """Shows new-version notice + changelog. Two buttons: 立即升级 / 稍后再说."""

    upgrade_requested = pyqtSignal()

    def __init__(self, info: UpdateInfo, current_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发现新版本")
        self.resize(620, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        # Header summary
        self.summary_label = StrongBodyLabel(
            f"新版本：v{info.version}    （当前：v{current_version}）",
            self,
        )
        root.addWidget(self.summary_label)

        published = BodyLabel(f"发布时间：{info.published_at}", self)
        root.addWidget(published)

        # Changelog
        cl_label = StrongBodyLabel("变更日志", self)
        root.addWidget(cl_label)

        self.changelog_view = QTextBrowser(self)
        self.changelog_view.setOpenExternalLinks(True)
        self.changelog_view.setMarkdown(info.changelog or "(无)")
        root.addWidget(self.changelog_view, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.later_button = QPushButton("稍后再说", self)
        self.later_button.clicked.connect(self.reject)
        btn_row.addWidget(self.later_button)
        self.upgrade_button = PrimaryPushButton("立即升级", self)
        self.upgrade_button.clicked.connect(self._on_upgrade)
        btn_row.addWidget(self.upgrade_button)
        root.addLayout(btn_row)

    def _on_upgrade(self) -> None:
        self.upgrade_requested.emit()
        self.accept()
