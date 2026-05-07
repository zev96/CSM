"""DedupPanel — two-metric row widget for the article right-side panel.

Layout:

    📊 内容查重           ⟳ 重新计算
    历史重复率   12% ▓▓░░░░░░  ⓘ
    素材引用率   38% ▓▓▓▓░░░░  ⓘ

The panel is purely presentational. It exposes two signals:
- ``recalculate_requested()`` — user clicked ⟳
- ``drilldown_requested(kind: str)`` — user clicked ⓘ for "history" or "vault"
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
)
from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, PushButton, ToolButton, FluentIcon,
)

from csm_core.dedup.report import DuplicateReport

_PERCENT_PLACEHOLDER = "—"


class _MetricRow(QWidget):
    """One labelled metric row with progress bar + drill button."""

    drill_requested = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.label = BodyLabel(label, self)
        self.label.setMinimumWidth(72)
        lay.addWidget(self.label)

        self.value_label = StrongBodyLabel(_PERCENT_PLACEHOLDER, self)
        self.value_label.setMinimumWidth(50)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.value_label)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar, 1)

        self.drill_button = ToolButton(FluentIcon.INFO, self)
        self.drill_button.setToolTip("查看详情")
        self.drill_button.setEnabled(False)
        self.drill_button.clicked.connect(self.drill_requested.emit)
        lay.addWidget(self.drill_button)


class DedupPanel(QWidget):
    """Right-side panel showing 历史重复率 + 素材引用率."""

    recalculate_requested = pyqtSignal()
    drilldown_requested = pyqtSignal(str)  # "history" | "vault"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DedupPanel")
        self.setStyleSheet("#DedupPanel { background: transparent; }")
        self._green_threshold = 15
        self._yellow_threshold = 30
        self._disabled_msg: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Header row: title + 重新计算 button
        header = QHBoxLayout()
        header.setSpacing(6)
        title = StrongBodyLabel("📊 内容查重", self)
        header.addWidget(title)
        header.addStretch(1)
        self.recalc_button = PushButton(FluentIcon.SYNC, "重新计算", self)
        self.recalc_button.setFixedHeight(26)
        self.recalc_button.clicked.connect(self.recalculate_requested.emit)
        header.addWidget(self.recalc_button)
        root.addLayout(header)

        # 历史重复率行
        self._history_row = _MetricRow("历史重复率", self)
        self._history_row.drill_requested.connect(
            lambda: self.drilldown_requested.emit("history")
        )
        root.addWidget(self._history_row)

        # 素材引用率行
        self._vault_row = _MetricRow("素材引用率", self)
        self._vault_row.drill_requested.connect(
            lambda: self.drilldown_requested.emit("vault")
        )
        root.addWidget(self._vault_row)

        # Hint label (used for disabled state messages)
        self._hint_label = QLabel("", self)
        self._hint_label.setStyleSheet("color: rgba(30,28,25,0.45); font-size: 11px;")
        self._hint_label.setVisible(False)
        root.addWidget(self._hint_label)

    # ── Public API ──────────────────────────────────────────────────────
    @property
    def history_value_label(self):
        return self._history_row.value_label

    @property
    def vault_value_label(self):
        return self._vault_row.value_label

    @property
    def history_drill_button(self):
        return self._history_row.drill_button

    @property
    def vault_drill_button(self):
        return self._vault_row.drill_button

    def set_thresholds(self, *, green: int, yellow: int) -> None:
        self._green_threshold = green
        self._yellow_threshold = yellow

    def set_report(self, report: DuplicateReport) -> None:
        row = self._history_row if report.corpus_kind == "history" else self._vault_row
        if report.text_length == 0:
            row.value_label.setText(_PERCENT_PLACEHOLDER)
            row.bar.setValue(0)
            row.drill_button.setEnabled(False)
            return
        pct = round(report.duplicate_ratio * 100)
        row.value_label.setText(f"{pct}%")
        row.bar.setValue(min(100, pct))
        row.drill_button.setEnabled(True)
        color = self._color_for(pct)
        row.value_label.setStyleSheet(
            f"color: {color}; background: transparent;"
        )

    def set_disabled_message(self, msg: str) -> None:
        self._disabled_msg = msg
        self.recalc_button.setEnabled(False)
        self._history_row.drill_button.setEnabled(False)
        self._vault_row.drill_button.setEnabled(False)
        self._hint_label.setText(msg)
        self._hint_label.setVisible(True)

    def clear_disabled_message(self) -> None:
        self._disabled_msg = None
        self.recalc_button.setEnabled(True)
        self._hint_label.setVisible(False)

    # ── Internal ────────────────────────────────────────────────────────
    def _color_for(self, pct: int) -> str:
        if pct < self._green_threshold:
            return "#2f6f5e"   # green
        if pct < self._yellow_threshold:
            return "#b89f3e"   # yellow
        return "#c0524b"       # red
