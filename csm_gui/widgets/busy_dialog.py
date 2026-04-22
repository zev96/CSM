"""Modal busy indicator for long-running LLM operations.

Shown while polish (and potentially other blocking steps) runs, so the user
can't trigger a second request mid-flight and the UI visibly reports that
work is in progress. Dismissed by the caller (``close()``) when the worker
emits its finished / failed signal.
"""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import IndeterminateProgressRing, BodyLabel, SubtitleLabel


class BusyDialog(QDialog):
    def __init__(self, title: str = "处理中", message: str = "请稍候…", parent=None):
        super().__init__(parent)
        # Frameless + modal so the user sees only the spinner and cannot
        # interact with the underlying window until we close it.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.CustomizeWindowHint
        )
        self.setModal(True)
        self.setWindowTitle(title)
        self.setFixedSize(320, 160)

        self._title_label = SubtitleLabel(title, self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label = BodyLabel(message, self)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner = IndeterminateProgressRing(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)
        root.addWidget(self._title_label)
        root.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._message_label)

    def set_message(self, message: str) -> None:
        self._message_label.setText(message)

    def keyPressEvent(self, event) -> None:
        # Suppress Esc — the dialog is dismissed programmatically when the
        # worker finishes, not by the user.
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        # Block the X / window-close path; only programmatic ``accept()`` or
        # ``reject()`` from the owner should dismiss this dialog.
        if not getattr(self, "_allow_close", False):
            event.ignore()
            return
        super().closeEvent(event)

    def dismiss(self) -> None:
        """Allow and trigger close. Call from the signal handler."""
        self._allow_close = True
        self.accept()
