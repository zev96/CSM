"""Advanced-config dialog for paragraph blocks.

Opens from the ⚙ button on a paragraph row in the slot tree. Bundles the
three logical field groups (筛选 / 采样 / 依赖) into one ``MessageBoxBase``
subclass. Each section is an independent widget that reads and writes the
same ``_BlockNode`` instance directly — the dialog itself just plumbs them.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QFrame,
)
from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, CaptionLabel,
    LineEdit, SpinBox, CheckBox, ToolButton, PushButton,
    EditableComboBox, FluentIcon, MessageBoxBase, SubtitleLabel,
)

if TYPE_CHECKING:
    from .slot_tree_widget import _BlockNode


# ── Filter section ────────────────────────────────────────────────────────────

def _parse_value(text: str) -> Any:
    """Parse the user's value input into list[str] or str or None.

    - ``""`` → ``None`` (caller drops the key)
    - ``"foo"`` → ``"foo"``
    - ``"foo, bar"`` → ``["foo", "bar"]``
    """
    parts = [p.strip() for p in text.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return parts


def _format_value(v: Any) -> str:
    """Inverse of ``_parse_value`` — display a filter value as editable text."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if v is None:
        return ""
    return str(v)


class _FilterSection(QWidget):
    """Key-value table for the filter dict."""

    def __init__(self, node, fm_candidates: dict[str, list[str]], parent=None):
        super().__init__(parent)
        self._node = node
        self._fm_candidates = fm_candidates
        self._rows: list[dict[str, Any]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(CaptionLabel("键"), 2)
        header.addWidget(CaptionLabel("值（多值用英文逗号分隔）"), 5)
        header.addWidget(CaptionLabel(""), 0)
        outer.addLayout(header)

        self._rows_host = QWidget(self)
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(4)
        outer.addWidget(self._rows_host)

        add_btn = PushButton(FluentIcon.ADD, "添加键", self)
        add_btn.clicked.connect(self._on_add_row)
        add_row = QHBoxLayout()
        add_row.addWidget(add_btn)
        add_row.addStretch(1)
        outer.addLayout(add_row)

        for k, v in (node.filter_cond or {}).items():
            self._append_row(k, _format_value(v))

    def rows_for_test(self) -> list[dict]:
        return [
            {
                "key": r["key_edit"].currentText(),
                "value": r["value_edit"].currentText(),
                "key_edit": r["key_edit"],
                "value_edit": r["value_edit"],
            }
            for r in self._rows
        ]

    def save_to_node(self) -> None:
        out: dict[str, Any] = {}
        for r in self._rows:
            key = r["key_edit"].currentText().strip()
            if not key:
                continue
            value = _parse_value(r["value_edit"].currentText())
            if value is None:
                continue
            out[key] = value
        self._node.filter_cond = out

    def _append_row(self, key: str = "", value: str = "") -> None:
        row_w = QWidget(self._rows_host)
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)

        key_edit = EditableComboBox(row_w)
        key_edit.addItems(sorted(self._fm_candidates.keys()))
        key_edit.setText(key)
        key_edit.setPlaceholderText("如：素材类型")
        row_lay.addWidget(key_edit, 2)

        value_edit = EditableComboBox(row_w)
        value_edit.setPlaceholderText("如：引言痛点, 引言期待")

        def _on_key_changed(_text: str, ve=value_edit, ke=key_edit):
            current = ve.currentText()
            ve.clear()
            vals = self._fm_candidates.get(ke.currentText().strip(), [])
            ve.addItems(vals)
            ve.setCurrentText(current)
        key_edit.currentTextChanged.connect(_on_key_changed)
        _on_key_changed(key)
        value_edit.setText(value)
        row_lay.addWidget(value_edit, 5)

        del_btn = ToolButton(FluentIcon.DELETE, row_w)
        del_btn.setFixedSize(28, 28)
        del_btn.clicked.connect(
            lambda _=False, _rw=row_w: self._remove_row_by_widget(_rw)
        )
        row_lay.addWidget(del_btn)

        self._rows_lay.addWidget(row_w)
        self._rows.append({
            "key_edit": key_edit,
            "value_edit": value_edit,
            "row_widget": row_w,
        })

    def _on_add_row(self) -> None:
        self._append_row("", "")

    def _remove_row(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows.pop(index)
        self._rows_lay.removeWidget(row["row_widget"])
        row["row_widget"].setParent(None)
        row["row_widget"].deleteLater()

    def _remove_row_by_widget(self, row_widget: QWidget) -> None:
        for i, r in enumerate(self._rows):
            if r["row_widget"] is row_widget:
                self._remove_row(i)
                return
