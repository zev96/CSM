"""Rank-fell-out alert card.

Shown above the monitor table when a task's most recent run fired the
alert. Clicking "生成对标内容" emits ``generate_requested`` with the
keyword + competitor-snippet payload, which MainWindow turns into a
navigation to ArticlePage with prefilled fields. The card is dismissable
via "稍后处理" — that just hides the widget; storage already records the
alert so a later check can re-render the card.

Strict UI rule: NO Emoji here. Status icon comes from FluentIcon.RINGER.
"""
from __future__ import annotations
from typing import Any

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CardWidget, FluentIcon, IconWidget, PrimaryPushButton,
    PushButton, StrongBodyLabel,
)


class RankAlertCard(CardWidget):
    """Banner card for a single alert. The page may host several stacked."""

    generate_requested = pyqtSignal(int, dict)  # task_id, prefill payload
    dismissed = pyqtSignal(int)  # task_id

    def __init__(
        self,
        task_id: int,
        task_name: str,
        rank_text: str,
        prefill: dict[str, Any],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._task_id = task_id
        self._prefill = prefill

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(14)

        # Leading icon — FluentIcon.RINGER (a bell). Sized to align with
        # two lines of text on the right.
        icon = IconWidget(FluentIcon.RINGER, self)
        icon.setFixedSize(28, 28)
        outer.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        # Text column — title + body, no emoji.
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = StrongBodyLabel(f"排名预警：{task_name}", self)
        body = BodyLabel(rank_text, self)
        body.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(body)
        outer.addLayout(text_col, 1)

        # Action buttons.
        gen_btn = PrimaryPushButton(FluentIcon.SEND, "生成对标内容", self)
        gen_btn.clicked.connect(self._on_generate)
        outer.addWidget(gen_btn)

        dismiss_btn = PushButton("稍后处理", self)
        dismiss_btn.clicked.connect(self._on_dismiss)
        outer.addWidget(dismiss_btn)

    def _on_generate(self) -> None:
        self.generate_requested.emit(self._task_id, self._prefill)

    def _on_dismiss(self) -> None:
        self.dismissed.emit(self._task_id)
