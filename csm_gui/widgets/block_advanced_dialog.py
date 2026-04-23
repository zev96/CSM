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


# ── Sample section ────────────────────────────────────────────────────────────

class _SampleSection(QWidget):
    """Edit pick_notes / pick_variants_per_note / unique_notes."""

    def __init__(self, node, parent=None):
        super().__init__(parent)
        self._node = node

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Row 1: pick_notes
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(BodyLabel("取笔记数："))
        self._min_spin = SpinBox(self)
        self._min_spin.setRange(1, 20)
        self._min_spin.setMaximumWidth(80)
        row1.addWidget(self._min_spin)

        self._range_checkbox = CheckBox("启用随机区间", self)
        self._range_checkbox.toggled.connect(self._on_range_toggled)
        row1.addWidget(self._range_checkbox)

        self._max_label = BodyLabel("最多：", self)
        row1.addWidget(self._max_label)
        self._max_spin = SpinBox(self)
        self._max_spin.setRange(1, 20)
        self._max_spin.setMaximumWidth(80)
        row1.addWidget(self._max_spin)
        row1.addStretch(1)
        outer.addLayout(row1)

        # Row 2: pick_variants
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(BodyLabel("每条笔记取变体数："))
        self._variants_spin = SpinBox(self)
        self._variants_spin.setRange(1, 9)
        self._variants_spin.setMaximumWidth(80)
        row2.addWidget(self._variants_spin)
        row2.addStretch(1)
        outer.addLayout(row2)

        # Row 3: unique_notes
        self._unique_checkbox = CheckBox("整篇不重复笔记（unique_notes）", self)
        self._unique_checkbox.setToolTip(
            "父段落与子段落不重复同一笔记（unique_notes）"
        )
        outer.addWidget(self._unique_checkbox)

        self._load_from_node()

    def save_to_node(self) -> None:
        if self._range_checkbox.isChecked() and self._max_spin.value() > self._min_spin.value():
            self._node.pick_notes = {
                "random_between": [self._min_spin.value(), self._max_spin.value()],
            }
        else:
            self._node.pick_notes = self._min_spin.value()
        self._node.pick_variants = self._variants_spin.value()
        self._node.unique_notes = self._unique_checkbox.isChecked()

    def _load_from_node(self) -> None:
        pick = self._node.pick_notes
        if isinstance(pick, dict) and "random_between" in pick:
            rb = pick["random_between"] or [1, 1]
            mn = rb[0] if len(rb) >= 1 else 1
            mx = rb[1] if len(rb) >= 2 else mn
            self._min_spin.setValue(int(mn))
            self._max_spin.setValue(int(mx))
            self._range_checkbox.setChecked(True)
        else:
            mn = int(pick) if isinstance(pick, int) else 1
            self._min_spin.setValue(mn)
            self._max_spin.setValue(max(mn + 1, 2))
            self._range_checkbox.setChecked(False)
        self._on_range_toggled(self._range_checkbox.isChecked())

        self._variants_spin.setValue(int(getattr(self._node, "pick_variants", 1) or 1))
        self._unique_checkbox.setChecked(bool(getattr(self._node, "unique_notes", False)))

    def _on_range_toggled(self, checked: bool) -> None:
        self._max_label.setVisible(checked)
        self._max_spin.setVisible(checked)


# ── Depends section ───────────────────────────────────────────────────────────

_SEARCH_THRESHOLD = 10


class _DependsSection(QWidget):
    """Multi-select list of block_ids the current node depends on."""

    def __init__(
        self,
        node,
        all_blocks: list[tuple[str, str, Any]],
        parent_widget=None,
    ):
        super().__init__(parent_widget)
        self._node = node
        self._checkboxes: list[CheckBox] = []
        self._block_ids_ordered: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        excluded = self._collect_excluded(node)
        # Identity-based filter: _BlockNode is a dataclass, so __eq__ would
        # field-compare, potentially matching unrelated blocks with the same
        # defaults. Use id() for strict identity.
        candidates = [
            (bid, label) for (bid, label, ref) in all_blocks
            if id(ref) not in excluded
        ]

        self._search_edit = LineEdit(self)
        self._search_edit.setPlaceholderText("搜索 block_id 或标签…")
        self._search_edit.textChanged.connect(self._on_search)
        outer.addWidget(self._search_edit)
        if len(candidates) <= _SEARCH_THRESHOLD:
            self._search_edit.hide()

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget(scroll)
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(2)

        existing = set(node.depends_on or [])
        for bid, label in candidates:
            cb = CheckBox(f"{bid} — {label}", host)
            cb.setChecked(bid in existing)
            host_lay.addWidget(cb)
            self._checkboxes.append(cb)
            self._block_ids_ordered.append(bid)
        host_lay.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def save_to_node(self) -> None:
        selected = [
            bid for bid, cb in zip(self._block_ids_ordered, self._checkboxes)
            if cb.isChecked()
        ]
        self._node.depends_on = selected

    def checkboxes_for_test(self) -> list[CheckBox]:
        return list(self._checkboxes)

    @staticmethod
    def _collect_excluded(self_node) -> set[int]:
        excluded: set[int] = {id(self_node)}
        def walk(n):
            excluded.add(id(n))
            for c in getattr(n, "children", []) or []:
                walk(c)
        for c in getattr(self_node, "children", []) or []:
            walk(c)
        return excluded

    def _on_search(self, text: str) -> None:
        needle = text.strip().lower()
        for cb in self._checkboxes:
            if not needle:
                cb.setVisible(True)
            else:
                cb.setVisible(needle in cb.text().lower())


# ── Main dialog ───────────────────────────────────────────────────────────────

class BlockAdvancedDialog(MessageBoxBase):
    """Paragraph block advanced-config dialog.

    Reads ``node`` on construction and writes back to the **same instance**
    when the user confirms. Cancelling leaves the node untouched.
    """

    def __init__(
        self,
        *,
        node,
        all_blocks: list[tuple[str, str, Any]],
        vault_root=None,
        parent=None,
    ):
        super().__init__(parent)
        self._node = node
        self.widget.setMinimumWidth(560)
        self.widget.setMinimumHeight(520)

        fm_candidates: dict[str, list[str]] = {}
        if vault_root is not None and getattr(node, "module", ""):
            try:
                from pathlib import Path
                from .slot_tree_widget import _scan_frontmatter
                mod_dir = Path(vault_root) / node.module
                if mod_dir.exists():
                    fm_candidates = _scan_frontmatter(mod_dir)
            except Exception:
                fm_candidates = {}

        label_hint = node.label or getattr(node, "block_id", "") or "段落"
        self.titleLabel = SubtitleLabel(f"段落高级设置 — {label_hint}", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.viewLayout.addWidget(StrongBodyLabel("筛选"))
        self._filter_section = _FilterSection(node, fm_candidates, parent=self)
        self.viewLayout.addWidget(self._filter_section)

        self.viewLayout.addWidget(StrongBodyLabel("采样"))
        self._sample_section = _SampleSection(node, parent=self)
        self.viewLayout.addWidget(self._sample_section)

        self.viewLayout.addWidget(StrongBodyLabel("依赖"))
        self._depends_section = _DependsSection(node, all_blocks, parent_widget=self)
        self.viewLayout.addWidget(self._depends_section, 1)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

    def accept(self) -> None:  # type: ignore[override]
        """Write every section back to the node, then close."""
        self._filter_section.save_to_node()
        self._sample_section.save_to_node()
        self._depends_section.save_to_node()
        super().accept()
