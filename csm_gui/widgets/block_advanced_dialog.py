"""Advanced-config dialog for paragraph blocks.

Opens from the ⚙ button on a paragraph row in the slot tree. Bundles the
three logical field groups (筛选 / 取值 / 链接) into one ``MessageBoxBase``
subclass. Each section is an independent widget that reads and writes the
same ``_BlockNode`` instance directly — the dialog itself just plumbs them.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
)
from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, CaptionLabel,
    LineEdit, SpinBox, CheckBox, ToolButton, PushButton,
    EditableComboBox, FluentIcon, MessageBoxBase, SubtitleLabel,
    DropDownPushButton, RoundMenu, Action,
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

        self._rows_host = QWidget(self)
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(4)
        outer.addWidget(self._rows_host)

        add_btn = PushButton(FluentIcon.ADD, "添加", self)
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
        row1.addWidget(BodyLabel("素材数量："))
        self._min_spin = SpinBox(self)
        self._min_spin.setRange(1, 20)
        self._min_spin.setFixedWidth(110)
        row1.addWidget(self._min_spin)

        self._range_checkbox = CheckBox("启用随机区间", self)
        self._range_checkbox.toggled.connect(self._on_range_toggled)
        row1.addWidget(self._range_checkbox)

        self._max_label = BodyLabel("最多：", self)
        row1.addWidget(self._max_label)
        self._max_spin = SpinBox(self)
        self._max_spin.setRange(1, 20)
        self._max_spin.setFixedWidth(110)
        row1.addWidget(self._max_spin)
        row1.addStretch(1)
        outer.addLayout(row1)

        # Rows 2 + 3: paragraph-only fields (wrapped so they can be hidden)
        self._para_only_box = QWidget(self)
        po_lay = QVBoxLayout(self._para_only_box)
        po_lay.setContentsMargins(0, 0, 0, 0)
        po_lay.setSpacing(6)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(BodyLabel("子素材随机数量："))
        self._variants_spin = SpinBox(self._para_only_box)
        self._variants_spin.setRange(1, 9)
        self._variants_spin.setFixedWidth(110)
        row2.addWidget(self._variants_spin)
        row2.addStretch(1)
        po_lay.addLayout(row2)

        self._unique_checkbox = CheckBox("不重复素材", self._para_only_box)
        self._unique_checkbox.setToolTip(
            "父段落与子段落不重复同一素材"
        )
        po_lay.addWidget(self._unique_checkbox)

        outer.addWidget(self._para_only_box)

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

    def set_paragraph_only_fields_visible(self, visible: bool) -> None:
        self._para_only_box.setVisible(visible)


# ── Depends section ───────────────────────────────────────────────────────────

_SEARCH_THRESHOLD = 10


class _DependsSection(QWidget):
    """Dropdown multi-select for block depends_on links."""

    def __init__(
        self,
        node,
        all_blocks: list[tuple[str, str, Any]],
        parent_widget=None,
    ):
        super().__init__(parent_widget)
        self._node = node
        self._candidates: list[tuple[str, str]] = []  # [(bid, label)]
        self._checked: set[str] = set(node.depends_on or [])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        excluded = self._collect_excluded(node)
        self._candidates = [
            (bid, label) for (bid, label, ref) in all_blocks
            if id(ref) not in excluded
        ]

        self._search_edit = LineEdit(self)
        self._search_edit.setPlaceholderText("搜索名称…")
        outer.addWidget(self._search_edit)
        if len(self._candidates) <= _SEARCH_THRESHOLD:
            self._search_edit.hide()

        self._dropdown_btn = DropDownPushButton(self._button_text(), self)
        self._dropdown_btn.clicked.connect(self._open_menu)
        outer.addWidget(self._dropdown_btn)

    def _button_text(self) -> str:
        if not self._checked:
            return "未链接"
        ordered = [lbl for bid, lbl in self._candidates if bid in self._checked]
        joined = "、".join(ordered)
        return joined if len(joined) <= 40 else joined[:38] + "…"

    def _filtered_candidates(self) -> list[tuple[str, str]]:
        """Return candidates filtered by the current search text."""
        needle = self._search_edit.text().strip().lower()
        if not needle:
            return list(self._candidates)
        return [(bid, lbl) for bid, lbl in self._candidates if needle in lbl.lower()]

    def _open_menu(self) -> None:
        # RoundMenu matches the Fluent styling of the rest of the app;
        # plain QMenu rendered with the native Qt look that stood out
        # against the ComboBox / DropDownPushButton popups.
        menu = RoundMenu(parent=self._dropdown_btn)
        filtered = self._filtered_candidates()
        if not filtered:
            act = Action("（无匹配）")
            act.setEnabled(False)
            menu.addAction(act)
        else:
            for bid, label in filtered:
                act = Action(label, self)
                act.setCheckable(True)
                act.setChecked(bid in self._checked)
                act.triggered.connect(
                    lambda checked, _bid=bid: self._toggle(_bid, checked)
                )
                menu.addAction(act)
        menu.exec(self._dropdown_btn.mapToGlobal(
            self._dropdown_btn.rect().bottomLeft()
        ))

    def _toggle(self, bid: str, checked: bool) -> None:
        if checked:
            self._checked.add(bid)
        else:
            self._checked.discard(bid)
        self._dropdown_btn.setText(self._button_text())

    def save_to_node(self) -> None:
        ordered = [bid for bid, _lbl in self._candidates if bid in self._checked]
        self._node.depends_on = ordered

    @staticmethod
    def _collect_excluded(self_node) -> set[int]:
        excluded = {id(self_node)}
        def walk(n):
            excluded.add(id(n))
            for c in getattr(n, "children", []) or []:
                walk(c)
        for c in getattr(self_node, "children", []) or []:
            walk(c)
        return excluded

    # Test helpers
    def candidates_for_test(self) -> list[tuple[str, str]]:
        return list(self._candidates)

    def checked_for_test(self) -> set[str]:
        return set(self._checked)

    def set_checked_for_test(self, bid: str, checked: bool) -> None:
        self._toggle(bid, checked)


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

        self.viewLayout.addWidget(StrongBodyLabel("取值"))
        self._sample_section = _SampleSection(node, parent=self)
        self.viewLayout.addWidget(self._sample_section)

        self._depends_header_label = StrongBodyLabel("链接")
        self.viewLayout.addWidget(self._depends_header_label)
        self._depends_section = _DependsSection(node, all_blocks, parent_widget=self)
        self.viewLayout.addWidget(self._depends_section, 1)

        is_para = (node.kind == "paragraph")
        self._sample_section.set_paragraph_only_fields_visible(is_para)
        if not is_para:
            self._depends_header_label.hide()
            self._depends_section.hide()

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

    def accept(self) -> None:  # type: ignore[override]
        """Write every section back to the node, then close."""
        self._filter_section.save_to_node()
        self._sample_section.save_to_node()
        self._depends_section.save_to_node()
        super().accept()
