"""UpdateProgressDialog — modal progress + cancel during download."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QProgressBar, QPushButton,
)
from qfluentwidgets import BodyLabel


def _human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == "GB":
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{f:.1f} GB"


class UpdateProgressDialog(QDialog):
    """Progress dialog used during the download phase."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在下载新版本")
        self.setMinimumWidth(420)
        self._cancelled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        self.status_label = BodyLabel("准备下载…", self)
        root.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_button = QPushButton("取消", self)
        self.cancel_button.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_button)
        root.addLayout(btn_row)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = min(100, int(done * 100 / total))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.status_label.setText(
                f"已下载 {_human_bytes(done)} / {_human_bytes(total)} ({pct}%)"
            )
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate
            self.status_label.setText(f"已下载 {_human_bytes(done)}")

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _on_cancel(self) -> None:
        self._cancelled = True
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在取消…")
        self.cancel_requested.emit()
