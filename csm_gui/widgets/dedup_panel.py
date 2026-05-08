"""DedupPanel — two-metric row widget for the article right-side panel.

Layout (matches the right-side workspace 'eyebrow' style — quiet, small caps,
no icon):

    内容查重                           重新计算
    历史重复率                12% ▓▓░░░░░░  ⓘ
    素材引用率                38% ▓▓▓▓░░░░  ⓘ

The panel is purely presentational. It exposes two signals:
- ``recalculate_requested()`` — user clicked 重新计算
- ``drilldown_requested(kind: str)`` — user clicked ⓘ for "history" or "vault"
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
)
from qfluentwidgets import FluentIcon, ToolButton

from csm_core.dedup.report import DuplicateReport

_PERCENT_PLACEHOLDER = "—"

# Tokens — mirror workspace_side_panel.py
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT = "#2f6f5e"


def _eyebrow_style() -> str:
    """Same visual recipe as workspace_side_panel._section_eyebrow."""
    return (
        f"color: {_INK_3}; font-size: 11px; letter-spacing: 0.6px;"
        " font-weight: 600; background: transparent;"
    )


class _MetricRow(QWidget):
    """One labelled metric row with progress bar + drill button."""

    drill_requested = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.label = QLabel(label, self)
        self.label.setMinimumWidth(72)
        self.label.setStyleSheet(
            f"color: {_INK_2}; font-size: 12px; background: transparent;"
        )
        lay.addWidget(self.label)

        self.value_label = QLabel(_PERCENT_PLACEHOLDER, self)
        self.value_label.setMinimumWidth(44)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setStyleSheet(
            f"color: {_INK_3}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        lay.addWidget(self.value_label)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            "QProgressBar { background: rgba(30,28,25,0.06);"
            " border: none; border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {_INK_3}; border-radius: 3px; }}"
        )
        lay.addWidget(self.bar, 1)

        self.drill_button = ToolButton(FluentIcon.INFO, self)
        self.drill_button.setToolTip("查看详情")
        self.drill_button.setFixedSize(22, 22)
        self.drill_button.setEnabled(False)
        self.drill_button.setStyleSheet(
            "ToolButton { background: transparent; border: none; }"
            f"ToolButton:hover {{ background: {_INK_5}; border-radius: 4px; }}"
        )
        self.drill_button.clicked.connect(self.drill_requested.emit)
        lay.addWidget(self.drill_button)

    def set_bar_color(self, color: str) -> None:
        self.bar.setStyleSheet(
            "QProgressBar { background: rgba(30,28,25,0.06);"
            " border: none; border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        )


class _LinkButton(QPushButton):
    """Small, quiet text button — looks like a hyperlink, not a card.

    Used for the 重新计算 affordance so the dedup panel reads as a quiet
    metrics block instead of competing with the primary 润色 button above.
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(20)
        self.setFlat(True)
        self.setStyleSheet(
            "QPushButton {"
            f" color: {_ACCENT}; background: transparent; border: none;"
            " padding: 0 0; font-size: 11.5px; text-align: right;"
            "}"
            "QPushButton:hover { color: #1f5246; text-decoration: underline; }"
            "QPushButton:disabled { color: rgba(30,28,25,0.30); }"
        )


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

        # Header row: small-caps eyebrow + 重新计算 link button
        header = QHBoxLayout()
        header.setSpacing(6)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("内容查重", self)
        title.setStyleSheet(_eyebrow_style())
        header.addWidget(title)
        header.addStretch(1)
        self.recalc_button = _LinkButton("重新计算", self)
        self.recalc_button.clicked.connect(self.recalculate_requested.emit)
        header.addWidget(self.recalc_button)
        root.addLayout(header)

        # Spacer between eyebrow and rows for breathing room
        root.addSpacing(2)

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
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet(
            f"color: {_INK_3}; font-size: 11px; background: transparent;"
        )
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
            f"color: {color}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        row.set_bar_color(color)

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
