# Paragraph Advanced Config Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the UI for editing a paragraph block's advanced fields — `filter` / `pick_notes` (with `random_between`) / `pick_variants_per_note` / `unique_notes` / `depends_on` — in a single "⚙ 高级" dialog, plus an inline "➕ 加子块" button on paragraph rows.

**Architecture:** A new `BlockAdvancedDialog` (`MessageBoxBase` subclass) composed of three independent section widgets — `_FilterSection`, `_SampleSection`, `_DependsSection` — each with its own round-trip tests. `_BlockRow` in `slot_tree_widget.py` gets two new paragraph-only buttons (gear opens the dialog, plus wires to the existing `_add_child`). The dialog writes back to the **same** `_BlockNode` instance on confirm; cancel leaves state untouched.

**Tech Stack:** PyQt6, qfluentwidgets (`MessageBoxBase`, `EditableComboBox`, `SpinBox`, `CheckBox`, `LineEdit`), pytest + pytest-qt.

**Spec:** [docs/superpowers/specs/2026-04-23-paragraph-advanced-config-design.md](../specs/2026-04-23-paragraph-advanced-config-design.md)

**Test env note:** All pytest invocations use `.venv\Scripts\python.exe` (system Python has PyQt6 DLL issues).

**Files:**

Create:
- `csm_gui/widgets/block_advanced_dialog.py`
- `tests/gui/test_block_advanced_dialog.py`

Modify:
- `csm_gui/widgets/slot_tree_widget.py` (add `_collect_all_blocks` helper, two buttons on `_BlockRow`, dialog wiring)
- `tests/gui/test_slot_tree_widget.py` (new file — there isn't one yet; add focused tests for the row additions)

---

## Task 1: `SlotTreeWidget._collect_all_blocks` helper

The depends-on section needs a flat list of every block in the tree (plus a way to identify the "current" block by object reference so it and its descendants can be excluded from the candidate list). Add a small helper to `SlotTreeWidget` now — it's independent of the dialog and easy to unit-test in isolation.

**Files:**
- Modify: `csm_gui/widgets/slot_tree_widget.py`
- Create: `tests/gui/test_slot_tree_widget.py`

- [ ] **Step 1: Write the failing test**

Create `tests/gui/test_slot_tree_widget.py`:

```python
"""Tests for SlotTreeWidget helpers and row behaviors."""
from __future__ import annotations
from csm_gui.widgets.slot_tree_widget import SlotTreeWidget, _BlockNode


def _paragraph(bid: str, label: str, children=()) -> _BlockNode:
    n = _BlockNode(kind="paragraph", block_id=bid, label=label)
    n.children = list(children)
    return n


def test_collect_all_blocks_returns_flat_list_in_tree_order(qtbot):
    w = SlotTreeWidget()
    qtbot.addWidget(w)
    child1 = _paragraph("", "孩子A")
    child2 = _paragraph("", "孩子B")
    root1 = _paragraph("", "根1", children=[child1, child2])
    root2 = _paragraph("", "根2")
    w._roots = [root1, root2]

    collected = w._collect_all_blocks()
    assert [(bid, label) for bid, label, _ in collected] == [
        ("block_1", "根1"),
        ("block_1_1", "孩子A"),
        ("block_1_2", "孩子B"),
        ("block_2", "根2"),
    ]
    # Third tuple slot is the node reference itself (identity-preserving).
    assert collected[0][2] is root1
    assert collected[1][2] is child1
    assert collected[3][2] is root2
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_slot_tree_widget.py -v
```
Expected: FAIL — `AttributeError: 'SlotTreeWidget' object has no attribute '_collect_all_blocks'`.

- [ ] **Step 3: Implement `_collect_all_blocks`**

In `csm_gui/widgets/slot_tree_widget.py`, add a method to `SlotTreeWidget` (near `get_blocks`, before the `# ── Backward-compat aliases` comment):

```python
    def _collect_all_blocks(self) -> list[tuple[str, str, "_BlockNode"]]:
        """Recursively flatten all block nodes.

        Returns ``[(block_id, label, node_ref)]`` in tree (DFS) order. The
        block_id is computed the same way ``get_blocks`` does (``block_1``,
        ``block_1_2``, …), so UI can reference blocks by the id they'll
        have once the template saves. ``label`` falls back to ``block_id``
        for blocks without a label (e.g. heading / literal).
        """
        out: list[tuple[str, str, "_BlockNode"]] = []

        def walk(nodes: list["_BlockNode"], parent_bid: str) -> None:
            for i, n in enumerate(nodes):
                bid = f"{parent_bid}_{i + 1}" if parent_bid else f"block_{i + 1}"
                label = n.label or getattr(n, "text", "") or bid
                out.append((bid, label, n))
                if n.kind == "paragraph" and n.children:
                    walk(n.children, bid)

        walk(self._roots, "")
        return out
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_slot_tree_widget.py -v
```
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/slot_tree_widget.py tests/gui/test_slot_tree_widget.py
git commit -m "feat(gui): SlotTreeWidget._collect_all_blocks helper

Flatten the block tree into [(block_id, label, node_ref)] for the
upcoming depends_on multi-select UI."
```

---

## Task 2: `_FilterSection` widget

The filter editor — a key-value table where each row is `[键 EditableComboBox] [值 EditableComboBox] [🗑]`, with a `➕` button at the bottom. Key candidates come from the scanned module frontmatter; value candidates come from that key's seen values. Values are saved as a single string or a list depending on whether the user entered commas.

**Files:**
- Create: `csm_gui/widgets/block_advanced_dialog.py` (new file, `_FilterSection` only in this task)
- Modify: `tests/gui/test_block_advanced_dialog.py` (new file — create in this task)

- [ ] **Step 1: Write the failing test**

Create `tests/gui/test_block_advanced_dialog.py`:

```python
"""Tests for BlockAdvancedDialog and its section widgets."""
from __future__ import annotations
from csm_gui.widgets.slot_tree_widget import _BlockNode
from csm_gui.widgets.block_advanced_dialog import _FilterSection


def _para_node(**kw) -> _BlockNode:
    n = _BlockNode(kind="paragraph")
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def test_filter_section_loads_existing_dict(qtbot):
    node = _para_node(filter_cond={"素材类型": ["引言痛点", "引言期待"], "难度": "简单"})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    rows = w.rows_for_test()
    assert len(rows) == 2
    # Rows order follows dict insertion order.
    assert rows[0]["key"] == "素材类型"
    assert rows[0]["value"] == "引言痛点, 引言期待"
    assert rows[1]["key"] == "难度"
    assert rows[1]["value"] == "简单"


def test_filter_section_add_row_appends_blank_entry(qtbot):
    node = _para_node(filter_cond={})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    assert len(w.rows_for_test()) == 0
    w._on_add_row()
    rows = w.rows_for_test()
    assert len(rows) == 1
    assert rows[0]["key"] == ""
    assert rows[0]["value"] == ""


def test_filter_section_save_roundtrips_list_and_scalar(qtbot):
    node = _para_node(filter_cond={})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    w._on_add_row()
    w._on_add_row()
    rows = w.rows_for_test()
    rows[0]["key_edit"].setText("素材类型")
    rows[0]["value_edit"].setText("引言痛点, 引言期待")
    rows[1]["key_edit"].setText("难度")
    rows[1]["value_edit"].setText("简单")
    w.save_to_node()
    assert node.filter_cond == {
        "素材类型": ["引言痛点", "引言期待"],
        "难度": "简单",
    }


def test_filter_section_save_drops_empty_values_and_keys(qtbot):
    node = _para_node(filter_cond={"旧键": "旧值"})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    rows = w.rows_for_test()
    # Blank out the only existing row's value.
    rows[0]["value_edit"].setText("")
    w._on_add_row()
    # New row: key filled, value blank.
    new_row = w.rows_for_test()[1]
    new_row["key_edit"].setText("另一键")
    new_row["value_edit"].setText("")
    w.save_to_node()
    assert node.filter_cond == {}


def test_filter_section_remove_row(qtbot):
    node = _para_node(filter_cond={"a": "1", "b": "2"})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    assert len(w.rows_for_test()) == 2
    w._remove_row(0)
    assert len(w.rows_for_test()) == 1
    assert w.rows_for_test()[0]["key"] == "b"
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'csm_gui.widgets.block_advanced_dialog'`.

- [ ] **Step 3: Create the module skeleton + implement `_FilterSection`**

Create `csm_gui/widgets/block_advanced_dialog.py`:

```python
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
        self._fm_candidates = fm_candidates  # {key: [values]}
        self._rows: list[dict[str, Any]] = []  # each: {key_edit, value_edit, row_widget}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(CaptionLabel("键"), 2)
        header.addWidget(CaptionLabel("值（多值用英文逗号分隔）"), 5)
        header.addWidget(CaptionLabel(""), 0)
        outer.addLayout(header)

        # Rows container
        self._rows_host = QWidget(self)
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(4)
        outer.addWidget(self._rows_host)

        # Add-row button
        add_btn = PushButton(FluentIcon.ADD, "添加键", self)
        add_btn.clicked.connect(self._on_add_row)
        add_row = QHBoxLayout()
        add_row.addWidget(add_btn)
        add_row.addStretch(1)
        outer.addLayout(add_row)

        # Load existing filter_cond
        for k, v in (node.filter_cond or {}).items():
            self._append_row(k, _format_value(v))

    # --- public test helpers --------------------------------------------------

    def rows_for_test(self) -> list[dict]:
        """Return shallow snapshot of every row: key/value text + widgets."""
        return [
            {
                "key": r["key_edit"].text(),
                "value": r["value_edit"].text(),
                "key_edit": r["key_edit"],
                "value_edit": r["value_edit"],
            }
            for r in self._rows
        ]

    def save_to_node(self) -> None:
        out: dict[str, Any] = {}
        for r in self._rows:
            key = r["key_edit"].text().strip()
            if not key:
                continue
            value = _parse_value(r["value_edit"].text())
            if value is None:
                continue
            out[key] = value
        self._node.filter_cond = out

    # --- internals ------------------------------------------------------------

    def _append_row(self, key: str = "", value: str = "") -> None:
        row_w = QWidget(self._rows_host)
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)

        key_edit = EditableComboBox(row_w)
        key_edit.addItems(sorted(self._fm_candidates.keys()))
        key_edit.setCurrentText(key)
        key_edit.setPlaceholderText("如：素材类型")
        row_lay.addWidget(key_edit, 2)

        value_edit = EditableComboBox(row_w)
        value_edit.setCurrentText(value)
        value_edit.setPlaceholderText("如：引言痛点, 引言期待")
        # When the key is known, seed the value dropdown with its candidates.
        def _on_key_changed(_text: str, ve=value_edit, ke=key_edit):
            ve.clear()
            vals = self._fm_candidates.get(ke.currentText().strip(), [])
            ve.addItems(vals)
        key_edit.currentTextChanged.connect(_on_key_changed)
        _on_key_changed(key)
        # Re-apply current text (addItems may have reset it).
        value_edit.setCurrentText(value)
        row_lay.addWidget(value_edit, 5)

        del_btn = ToolButton(FluentIcon.DELETE, row_w)
        del_btn.setFixedSize(28, 28)
        idx_placeholder = len(self._rows)
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/block_advanced_dialog.py tests/gui/test_block_advanced_dialog.py
git commit -m "feat(gui): _FilterSection — key-value editor for paragraph filter"
```

---

## Task 3: `_SampleSection` widget

pick_notes (`int` or `{random_between: [min, max]}`), pick_variants_per_note, and unique_notes — all in one section. The random-between UI is the interesting part: a checkbox reveals a second spinbox.

**Files:**
- Modify: `csm_gui/widgets/block_advanced_dialog.py` (append `_SampleSection`)
- Modify: `tests/gui/test_block_advanced_dialog.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/gui/test_block_advanced_dialog.py`:

```python
from csm_gui.widgets.block_advanced_dialog import _SampleSection


def test_sample_section_loads_int_pick(qtbot):
    node = _para_node(pick_notes=3, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    assert w._min_spin.value() == 3
    assert w._range_checkbox.isChecked() is False
    assert w._max_spin.isVisible() is False
    assert w._variants_spin.value() == 1
    assert w._unique_checkbox.isChecked() is False


def test_sample_section_loads_random_between(qtbot):
    node = _para_node(
        pick_notes={"random_between": [2, 5]},
        pick_variants=2,
        unique_notes=True,
    )
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    assert w._min_spin.value() == 2
    assert w._range_checkbox.isChecked() is True
    assert w._max_spin.isVisible() is True
    assert w._max_spin.value() == 5
    assert w._variants_spin.value() == 2
    assert w._unique_checkbox.isChecked() is True


def test_sample_section_save_int_when_range_disabled(qtbot):
    node = _para_node(pick_notes=1, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w._min_spin.setValue(4)
    w._variants_spin.setValue(2)
    w._unique_checkbox.setChecked(True)
    w.save_to_node()
    assert node.pick_notes == 4
    assert node.pick_variants == 2
    assert node.unique_notes is True


def test_sample_section_save_dict_when_range_enabled(qtbot):
    node = _para_node(pick_notes=1, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w._min_spin.setValue(2)
    w._range_checkbox.setChecked(True)
    w._max_spin.setValue(5)
    w.save_to_node()
    assert node.pick_notes == {"random_between": [2, 5]}


def test_sample_section_save_int_when_range_min_equals_max(qtbot):
    node = _para_node(pick_notes=1, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w._min_spin.setValue(3)
    w._range_checkbox.setChecked(True)
    w._max_spin.setValue(3)
    w.save_to_node()
    assert node.pick_notes == 3


def test_sample_section_toggle_range_shows_and_hides_max(qtbot):
    node = _para_node(pick_notes=2, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w.show()
    assert w._max_spin.isVisible() is False
    w._range_checkbox.setChecked(True)
    assert w._max_spin.isVisible() is True
    w._range_checkbox.setChecked(False)
    assert w._max_spin.isVisible() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: FAIL — `ImportError: cannot import name '_SampleSection'`.

- [ ] **Step 3: Implement `_SampleSection`**

Append to `csm_gui/widgets/block_advanced_dialog.py` (after `_FilterSection`):

```python
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

    # --- public API -----------------------------------------------------------

    def save_to_node(self) -> None:
        if self._range_checkbox.isChecked() and self._max_spin.value() > self._min_spin.value():
            self._node.pick_notes = {
                "random_between": [self._min_spin.value(), self._max_spin.value()],
            }
        else:
            # Range disabled, or min == max → degrade to int.
            self._node.pick_notes = self._min_spin.value()
        self._node.pick_variants = self._variants_spin.value()
        self._node.unique_notes = self._unique_checkbox.isChecked()

    # --- internals ------------------------------------------------------------

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
            self._min_spin.setValue(int(pick) if isinstance(pick, int) else 1)
            self._max_spin.setValue(
                max(int(pick) if isinstance(pick, int) else 1, 1) + 1,
            )
            self._range_checkbox.setChecked(False)
        self._on_range_toggled(self._range_checkbox.isChecked())

        self._variants_spin.setValue(int(getattr(self._node, "pick_variants", 1) or 1))
        self._unique_checkbox.setChecked(bool(getattr(self._node, "unique_notes", False)))

    def _on_range_toggled(self, checked: bool) -> None:
        self._max_label.setVisible(checked)
        self._max_spin.setVisible(checked)
```

- [ ] **Step 4: Run tests**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: PASS (11 passed: 5 filter + 6 sample).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/block_advanced_dialog.py tests/gui/test_block_advanced_dialog.py
git commit -m "feat(gui): _SampleSection — pick_notes / pick_variants / unique_notes editor"
```

---

## Task 4: `_DependsSection` widget

A scrollable list of checkboxes, one per candidate block. Excludes the current block itself and all its descendants. Shows a search box when the candidate count exceeds 10.

**Files:**
- Modify: `csm_gui/widgets/block_advanced_dialog.py` (append `_DependsSection`)
- Modify: `tests/gui/test_block_advanced_dialog.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/gui/test_block_advanced_dialog.py`:

```python
from csm_gui.widgets.block_advanced_dialog import _DependsSection
from csm_gui.widgets.slot_tree_widget import _BlockNode


def test_depends_section_excludes_self_and_descendants(qtbot):
    parent = _BlockNode(kind="paragraph", label="父")
    child_a = _BlockNode(kind="paragraph", label="子A")
    grand = _BlockNode(kind="paragraph", label="孙")
    child_a.children = [grand]
    parent.children = [child_a]
    sibling = _BlockNode(kind="paragraph", label="兄弟")
    # all_blocks as returned by _collect_all_blocks.
    all_blocks = [
        ("block_1", "父", parent),
        ("block_1_1", "子A", child_a),
        ("block_1_1_1", "孙", grand),
        ("block_2", "兄弟", sibling),
    ]
    w = _DependsSection(parent, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    labels = [c.text() for c in w.checkboxes_for_test()]
    # Only the sibling is a candidate; self + 2 descendants are excluded.
    assert labels == ["block_2 — 兄弟"]


def test_depends_section_checks_existing_depends_on(qtbot):
    self_node = _BlockNode(kind="paragraph", label="我")
    self_node.depends_on = ["block_2"]
    other_a = _BlockNode(kind="paragraph", label="A")
    other_b = _BlockNode(kind="paragraph", label="B")
    all_blocks = [
        ("block_1", "我", self_node),
        ("block_2", "A", other_a),
        ("block_3", "B", other_b),
    ]
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    boxes = w.checkboxes_for_test()
    assert boxes[0].isChecked() is True    # block_2
    assert boxes[1].isChecked() is False   # block_3


def test_depends_section_save_preserves_order(qtbot):
    self_node = _BlockNode(kind="paragraph")
    a = _BlockNode(kind="paragraph")
    b = _BlockNode(kind="paragraph")
    c = _BlockNode(kind="paragraph")
    all_blocks = [
        ("block_1", "self", self_node),
        ("block_2", "A", a),
        ("block_3", "B", b),
        ("block_4", "C", c),
    ]
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    boxes = w.checkboxes_for_test()
    boxes[0].setChecked(True)   # block_2
    boxes[2].setChecked(True)   # block_4
    w.save_to_node()
    assert self_node.depends_on == ["block_2", "block_4"]


def test_depends_section_search_box_hidden_when_few_candidates(qtbot):
    self_node = _BlockNode(kind="paragraph")
    all_blocks = [
        ("block_1", "self", self_node),
        ("block_2", "A", _BlockNode(kind="paragraph")),
    ]
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    assert w._search_edit.isHidden() is True


def test_depends_section_search_box_filters_candidates(qtbot):
    self_node = _BlockNode(kind="paragraph")
    all_blocks = [("block_1", "self", self_node)]
    # 11 candidates to trigger the search box.
    for i in range(2, 13):
        all_blocks.append((f"block_{i}", f"标签{i}", _BlockNode(kind="paragraph")))
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    assert w._search_edit.isHidden() is False
    # Filter by a substring only "标签5" matches.
    w._search_edit.setText("5")
    visible = [cb for cb in w.checkboxes_for_test() if cb.isVisible()]
    assert len(visible) == 1
    assert "标签5" in visible[0].text()
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: FAIL — `ImportError: cannot import name '_DependsSection'`.

- [ ] **Step 3: Implement `_DependsSection`**

Append to `csm_gui/widgets/block_advanced_dialog.py`:

```python
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
        candidates = [
            (bid, label) for (bid, label, ref) in all_blocks if ref not in excluded
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

    # --- public API -----------------------------------------------------------

    def save_to_node(self) -> None:
        selected = [
            bid for bid, cb in zip(self._block_ids_ordered, self._checkboxes)
            if cb.isChecked()
        ]
        self._node.depends_on = selected

    def checkboxes_for_test(self) -> list[CheckBox]:
        return list(self._checkboxes)

    # --- internals ------------------------------------------------------------

    @staticmethod
    def _collect_excluded(self_node) -> set[int]:
        """Return set of ``id(node)`` values for the node itself + descendants."""
        excluded = {id(self_node)}
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
```

**Note:** The excluded-set is tracked by `id(node)`, not object identity via `is` / `in` list — the membership test `ref not in excluded` in the list comprehension uses `__eq__`, which for `_BlockNode` (a dataclass) compares field-by-field and would wrongly exclude unrelated blocks with the same defaults. Fix by comparing `id()` values in the candidate filter. Replace the `candidates = [...]` line with:

```python
        candidates = [
            (bid, label) for (bid, label, ref) in all_blocks
            if id(ref) not in excluded
        ]
```

Make sure this is the version in your file. If the test `test_depends_section_excludes_self_and_descendants` passes without this change, fine — but with default-field dataclasses the safer identity check is via `id()`.

- [ ] **Step 4: Run tests**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: PASS (16 passed: 5 + 6 + 5).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/block_advanced_dialog.py tests/gui/test_block_advanced_dialog.py
git commit -m "feat(gui): _DependsSection — depends_on multi-select with search"
```

---

## Task 5: `BlockAdvancedDialog` — assemble the three sections

The dialog ties the sections together. On `accept()` each section writes back to the node; on `reject()` nothing changes.

**Files:**
- Modify: `csm_gui/widgets/block_advanced_dialog.py` (append `BlockAdvancedDialog`)
- Modify: `tests/gui/test_block_advanced_dialog.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/gui/test_block_advanced_dialog.py`:

```python
from csm_gui.widgets.block_advanced_dialog import BlockAdvancedDialog


def test_dialog_accept_writes_all_sections_back(qtbot):
    node = _BlockNode(
        kind="paragraph", label="test",
        filter_cond={}, pick_notes=1, pick_variants=1, unique_notes=False,
    )
    other = _BlockNode(kind="paragraph", label="other")
    all_blocks = [("block_1", "test", node), ("block_2", "other", other)]
    dlg = BlockAdvancedDialog(
        node=node, all_blocks=all_blocks, vault_root=None, parent=None,
    )
    qtbot.addWidget(dlg)
    # Filter: add a row.
    dlg._filter_section._on_add_row()
    row = dlg._filter_section.rows_for_test()[0]
    row["key_edit"].setText("素材类型")
    row["value_edit"].setText("引言痛点")
    # Sample: bump pick_notes to 5 with range.
    dlg._sample_section._min_spin.setValue(2)
    dlg._sample_section._range_checkbox.setChecked(True)
    dlg._sample_section._max_spin.setValue(5)
    dlg._sample_section._variants_spin.setValue(2)
    dlg._sample_section._unique_checkbox.setChecked(True)
    # Depends: check block_2.
    dlg._depends_section.checkboxes_for_test()[0].setChecked(True)

    dlg.accept()

    assert node.filter_cond == {"素材类型": "引言痛点"}
    assert node.pick_notes == {"random_between": [2, 5]}
    assert node.pick_variants == 2
    assert node.unique_notes is True
    assert node.depends_on == ["block_2"]


def test_dialog_reject_leaves_node_unchanged(qtbot):
    node = _BlockNode(
        kind="paragraph",
        filter_cond={"key": "val"},
        pick_notes=2, pick_variants=1, unique_notes=False,
        depends_on=["block_9"],
    )
    all_blocks = [("block_1", "self", node)]
    dlg = BlockAdvancedDialog(
        node=node, all_blocks=all_blocks, vault_root=None, parent=None,
    )
    qtbot.addWidget(dlg)
    # Fiddle with every section.
    dlg._filter_section._on_add_row()
    dlg._filter_section.rows_for_test()[-1]["key_edit"].setText("新键")
    dlg._sample_section._min_spin.setValue(9)
    dlg._sample_section._unique_checkbox.setChecked(True)

    dlg.reject()

    assert node.filter_cond == {"key": "val"}
    assert node.pick_notes == 2
    assert node.pick_variants == 1
    assert node.unique_notes is False
    assert node.depends_on == ["block_9"]


def test_dialog_title_shows_block_identity(qtbot):
    node = _BlockNode(kind="paragraph", label="我的段落")
    dlg = BlockAdvancedDialog(
        node=node, all_blocks=[("block_1", "我的段落", node)],
        vault_root=None, parent=None,
    )
    qtbot.addWidget(dlg)
    assert "我的段落" in dlg.titleLabel.text()
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: FAIL — `ImportError: cannot import name 'BlockAdvancedDialog'`.

- [ ] **Step 3: Implement `BlockAdvancedDialog`**

Append to `csm_gui/widgets/block_advanced_dialog.py`:

```python
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

        # Compute filter candidates from the module path (if vault_root + module set).
        fm_candidates: dict[str, list[str]] = {}
        if vault_root is not None and node.module:
            try:
                from pathlib import Path
                from .slot_tree_widget import _scan_frontmatter
                mod_dir = Path(vault_root) / node.module
                if mod_dir.exists():
                    fm_candidates = _scan_frontmatter(mod_dir)
            except Exception:
                fm_candidates = {}

        # Title
        label_hint = node.label or getattr(node, "block_id", "") or "段落"
        self.titleLabel = SubtitleLabel(f"段落高级设置 — {label_hint}", self)
        self.viewLayout.addWidget(self.titleLabel)

        # Filter section
        self.viewLayout.addWidget(StrongBodyLabel("筛选"))
        self._filter_section = _FilterSection(node, fm_candidates, parent=self)
        self.viewLayout.addWidget(self._filter_section)

        # Sample section
        self.viewLayout.addWidget(StrongBodyLabel("采样"))
        self._sample_section = _SampleSection(node, parent=self)
        self.viewLayout.addWidget(self._sample_section)

        # Depends section
        self.viewLayout.addWidget(StrongBodyLabel("依赖"))
        self._depends_section = _DependsSection(node, all_blocks, parent_widget=self)
        self.viewLayout.addWidget(self._depends_section, 1)

        # Buttons
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

    def accept(self) -> None:  # type: ignore[override]
        """Write every section back to the node, then close."""
        self._filter_section.save_to_node()
        self._sample_section.save_to_node()
        self._depends_section.save_to_node()
        super().accept()
```

- [ ] **Step 4: Run tests**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_block_advanced_dialog.py -v
```
Expected: PASS (19 passed).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/block_advanced_dialog.py tests/gui/test_block_advanced_dialog.py
git commit -m "feat(gui): BlockAdvancedDialog — compose filter/sample/depends sections"
```

---

## Task 6: Wire `⚙` + `➕` buttons into `_BlockRow`

Add two `TransparentToolButton`s to each paragraph row. The gear opens `BlockAdvancedDialog`; the plus calls `_add_child`. Both are hidden for non-paragraph kinds.

**Files:**
- Modify: `csm_gui/widgets/slot_tree_widget.py`
- Modify: `tests/gui/test_slot_tree_widget.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/gui/test_slot_tree_widget.py`:

```python
import pytest
from csm_gui.widgets.slot_tree_widget import SlotTreeWidget, _BlockNode


def _make_widget_with_root(qtbot, kind: str = "paragraph"):
    w = SlotTreeWidget()
    qtbot.addWidget(w)
    w.load_blocks([])
    # Force a root block of the given kind.
    w._roots = [_BlockNode(kind=kind, label="根")]
    w._rebuild()
    return w


def test_paragraph_row_shows_gear_and_add_child(qtbot):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    row = w._all_rows_for_test()[0]
    assert row._gear_btn.isVisible() is True
    assert row._add_child_btn.isVisible() is True


def test_non_paragraph_row_hides_gear_and_add_child(qtbot):
    w = _make_widget_with_root(qtbot, kind="heading")
    row = w._all_rows_for_test()[0]
    assert row._gear_btn.isVisible() is False
    assert row._add_child_btn.isVisible() is False


def test_kind_switch_to_paragraph_reveals_gear_and_add_child(qtbot):
    w = _make_widget_with_root(qtbot, kind="heading")
    row = w._all_rows_for_test()[0]
    # Switch the combo to paragraph (index 0 in BLOCK_KINDS).
    row._kind_combo.setCurrentIndex(0)
    assert row._gear_btn.isVisible() is True
    assert row._add_child_btn.isVisible() is True


def test_click_add_child_appends_child_and_expands(qtbot):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    root_node = w._roots[0]
    assert root_node.children == []
    assert root_node.expanded is False
    row = w._all_rows_for_test()[0]
    row._add_child_btn.click()
    assert len(root_node.children) == 1
    assert root_node.children[0].kind == "paragraph"
    assert root_node.expanded is True


def test_gear_opens_dialog_and_writes_back_on_accept(qtbot, monkeypatch):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    row = w._all_rows_for_test()[0]
    root_node = w._roots[0]

    # Intercept dialog: instead of exec'ing, accept immediately after
    # programmatic edit.
    captured = {}
    from csm_gui.widgets import block_advanced_dialog as mod
    real_cls = mod.BlockAdvancedDialog
    def fake_init(self, *, node, all_blocks, vault_root=None, parent=None):
        real_cls.__init__(
            self, node=node, all_blocks=all_blocks,
            vault_root=vault_root, parent=parent,
        )
        # Pre-set the UI to a deterministic state.
        self._sample_section._min_spin.setValue(7)
        self._sample_section._unique_checkbox.setChecked(True)
        captured["dlg"] = self
    monkeypatch.setattr(mod.BlockAdvancedDialog, "__init__", fake_init)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "exec", lambda self: self.accept() or 1)

    row._gear_btn.click()
    assert root_node.pick_notes == 7
    assert root_node.unique_notes is True


def test_gear_cancel_leaves_node_untouched(qtbot, monkeypatch):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    w._roots[0].pick_notes = 3
    w._roots[0].unique_notes = False
    row = w._all_rows_for_test()[0]

    from csm_gui.widgets import block_advanced_dialog as mod
    real_cls = mod.BlockAdvancedDialog
    def fake_init(self, *, node, all_blocks, vault_root=None, parent=None):
        real_cls.__init__(
            self, node=node, all_blocks=all_blocks,
            vault_root=vault_root, parent=parent,
        )
        self._sample_section._min_spin.setValue(9)
        self._sample_section._unique_checkbox.setChecked(True)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "__init__", fake_init)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "exec", lambda self: self.reject() or 0)

    row._gear_btn.click()
    assert w._roots[0].pick_notes == 3
    assert w._roots[0].unique_notes is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_slot_tree_widget.py -v
```
Expected: FAIL — attributes `_gear_btn` / `_add_child_btn` / `_all_rows_for_test` not found.

- [ ] **Step 3: Add `_all_rows_for_test` helper on `SlotTreeWidget`**

In `csm_gui/widgets/slot_tree_widget.py`, append this method to `SlotTreeWidget` (next to `_collect_all_blocks`):

```python
    def _all_rows_for_test(self) -> list["_BlockRow"]:
        """Test helper: flat list of every visible ``_BlockRow``."""
        rows: list[_BlockRow] = []
        for i in range(self._lo.count()):
            w = self._lo.itemAt(i).widget()
            if isinstance(w, _BlockRow):
                rows.append(w)
        return rows
```

- [ ] **Step 4: Add the two buttons to `_BlockRow`**

In `csm_gui/widgets/slot_tree_widget.py`, modify `_BlockRow.__init__`. Locate the current action-buttons loop (the one building DOWN / UP / DELETE):

```python
        # ── Action buttons ────────────────────────────────────────────────
        for icon, sig in [
            (FluentIcon.DOWN,   self.move_down),
            (FluentIcon.UP,     self.move_up),
            (FluentIcon.DELETE, self.delete_req),
        ]:
            btn = TransparentToolButton(icon, self)
            btn.setFixedSize(28, 28)
            btn.clicked.connect(sig)
            outer.addWidget(btn)
```

Replace that block with:

```python
        # ── Paragraph-only action buttons: advanced config + add child ───
        self._gear_btn = TransparentToolButton(FluentIcon.SETTING, self)
        self._gear_btn.setFixedSize(28, 28)
        self._gear_btn.setToolTip("高级配置（筛选 / 采样 / 依赖）")
        self._gear_btn.clicked.connect(self._on_gear_clicked)
        self._gear_btn.setVisible(node.kind == "paragraph")
        outer.addWidget(self._gear_btn)

        self._add_child_btn = TransparentToolButton(FluentIcon.ADD, self)
        self._add_child_btn.setFixedSize(28, 28)
        self._add_child_btn.setToolTip("添加子段落")
        self._add_child_btn.clicked.connect(self._on_add_child_clicked)
        self._add_child_btn.setVisible(node.kind == "paragraph")
        outer.addWidget(self._add_child_btn)

        # ── Generic action buttons ────────────────────────────────────────
        for icon, sig in [
            (FluentIcon.DOWN,   self.move_down),
            (FluentIcon.UP,     self.move_up),
            (FluentIcon.DELETE, self.delete_req),
        ]:
            btn = TransparentToolButton(icon, self)
            btn.setFixedSize(28, 28)
            btn.clicked.connect(sig)
            outer.addWidget(btn)
```

Now add a new `gear_requested` signal at the top of the `_BlockRow` class next to the others:

```python
    expand_toggled = pyqtSignal()
    move_up        = pyqtSignal()
    move_down      = pyqtSignal()
    delete_req     = pyqtSignal()
    data_changed   = pyqtSignal()
    gear_requested      = pyqtSignal()
    add_child_requested = pyqtSignal()
```

Add the two handler methods inside `_BlockRow`:

```python
    def _on_gear_clicked(self) -> None:
        self.gear_requested.emit()

    def _on_add_child_clicked(self) -> None:
        self.add_child_requested.emit()
```

Update `_on_kind_changed` to show/hide the new buttons alongside the expand chevron. Locate:

```python
    def _on_kind_changed(self, idx: int) -> None:
        new_kind = BLOCK_KINDS[idx]
        self._node.kind = new_kind
        self._stack.setCurrentIndex(idx)
        # Show/hide expand button based on kind
        self._expand_btn.setVisible(new_kind == "paragraph")
        self._update_expand_icon()
        self.data_changed.emit()
```

Replace with:

```python
    def _on_kind_changed(self, idx: int) -> None:
        new_kind = BLOCK_KINDS[idx]
        self._node.kind = new_kind
        self._stack.setCurrentIndex(idx)
        is_para = new_kind == "paragraph"
        self._expand_btn.setVisible(is_para)
        self._gear_btn.setVisible(is_para)
        self._add_child_btn.setVisible(is_para)
        self._update_expand_icon()
        self.data_changed.emit()
```

- [ ] **Step 5: Wire the new signals in `SlotTreeWidget._render_nodes`**

Locate in `SlotTreeWidget._render_nodes`:

```python
            row.expand_toggled.connect(lambda _n=node: self._on_toggle(_n))
            row.move_up.connect(
                lambda _nl=nodes, _i=i: self._move_node(_nl, _i, -1)
            )
            row.move_down.connect(
                lambda _nl=nodes, _i=i: self._move_node(_nl, _i, +1)
            )
            row.delete_req.connect(
                lambda _nl=nodes, _i=i: self._delete_node(_nl, _i)
            )
            row.data_changed.connect(self.slots_changed)
```

Append two more connections inside the same loop body:

```python
            row.gear_requested.connect(lambda _n=node: self._open_gear_dialog(_n))
            row.add_child_requested.connect(lambda _n=node: self._add_child(_n))
```

Add the `_open_gear_dialog` method near `_add_child`:

```python
    def _open_gear_dialog(self, node: _BlockNode) -> None:
        from .block_advanced_dialog import BlockAdvancedDialog
        all_blocks = self._collect_all_blocks()
        dlg = BlockAdvancedDialog(
            node=node,
            all_blocks=all_blocks,
            vault_root=self._vault_root,
            parent=self,
        )
        if dlg.exec():
            self._rebuild()
            self.slots_changed.emit()
```

- [ ] **Step 6: Run tests**

```
.venv\Scripts\python.exe -m pytest tests/gui/test_slot_tree_widget.py tests/gui/test_block_advanced_dialog.py -v
```
Expected: PASS (all — 6 row tests + 19 dialog tests).

- [ ] **Step 7: Full GUI regression**

```
.venv\Scripts\python.exe -m pytest tests/gui/ -q
```
Expected: all pass. If a pre-existing test broke because `_BlockRow` now emits/handles new signals, update only as needed (the additions should be purely additive).

- [ ] **Step 8: Full test suite**

```
.venv\Scripts\python.exe -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add csm_gui/widgets/slot_tree_widget.py tests/gui/test_slot_tree_widget.py
git commit -m "feat(gui): paragraph row — gear opens advanced dialog, plus adds child

Paragraph-only buttons: ⚙ wires to BlockAdvancedDialog (filter / sample /
depends), ➕ appends a child paragraph and expands the parent. Non-paragraph
rows stay unchanged."
```

---

## Task 7: Manual smoke test

No code changes. Verify the full flow in the GUI.

- [ ] **Step 1: Launch the app**

```
.venv\Scripts\python.exe -m csm_gui
```

- [ ] **Step 2: Open the template editor**

Navigate to the template manager page; pick `templates/daogou-changjing-renqun.json` (or any paragraph-heavy template).

- [ ] **Step 3: Verify paragraph rows show the new buttons**

Each paragraph row should display `[⚙] [➕]` before the existing `[↓] [↑] [🗑]`. Heading / literal / numbered_list / hero_brand / competitor_pool rows should show only the original 3 buttons.

- [ ] **Step 4: Open the advanced dialog**

Click ⚙ on a paragraph row. Dialog should appear with:
- Title showing the block label.
- `[筛选]` section: existing filter keys preloaded as rows.
- `[采样]` section: current pick_notes / variants / unique_notes reflected.
- `[依赖]` section: any existing `depends_on` checkboxes checked; self + descendants absent from the list.

- [ ] **Step 5: Edit filter**

Add a new row (➕ 添加键), pick a key from the dropdown (should be populated from the module's scanned frontmatter), type a value (comma-separated for multi-value). Click 确定. The template JSON preview (or save-and-reopen) should reflect the change.

- [ ] **Step 6: Edit sample**

Toggle "启用随机区间" on, set 取笔记数 = 2, 最多 = 4. Click 确定. Save template. Reopen: the dialog should re-load with the checkbox on and values preserved as `{random_between: [2, 4]}`.

- [ ] **Step 7: Edit depends**

Tick one or more candidate blocks. Click 确定. Save. The exported JSON's `depends_on` for that block should contain the checked ids in UI order.

- [ ] **Step 8: Cancel leaves state intact**

Reopen the dialog, change several fields, click 取消. Reopen again: all fields should show the previous (unchanged) values.

- [ ] **Step 9: Add child**

On a paragraph row, click ➕. A new child paragraph should appear indented underneath, and the parent's expand chevron should be open. Child should be editable like any paragraph (including its own ⚙).

- [ ] **Step 10: Non-paragraph rows unaffected**

Switch a row's kind from paragraph to heading via the kind combo. The ⚙ and ➕ buttons should disappear. Switch back — they should return.

---

## Self-Review Checklist

**Spec coverage:**
- [x] 行上控件改动 (gear + add_child, paragraph-only) — Task 6
- [x] 对话框结构 (三个分区 + 取消/确定) — Task 5
- [x] filter 键值表 + frontmatter 候选 + 多值解析 — Task 2
- [x] pick_notes int ↔ dict 切换 — Task 3
- [x] pick_variants 与 unique_notes — Task 3
- [x] depends_on 候选排除自身+子孙 + 搜索框 — Task 4
- [x] `_collect_all_blocks` 辅助 — Task 1
- [x] 取消不改 node — Task 5 (test_dialog_reject_leaves_node_unchanged)
- [x] 确认写回 node (同一实例) — Task 5
- [x] 测试清单 7 项 + 行行为 2 项 — Tasks 2-6

**Placeholder scan:** none.

**Type consistency:**
- `_FilterSection(node, fm_candidates, parent)` — Task 2 def, Task 5 call match.
- `_SampleSection(node, parent)` — Task 3 def, Task 5 call match.
- `_DependsSection(node, all_blocks, parent_widget=...)` — Task 4 def, Task 5 call match.
- `BlockAdvancedDialog(*, node, all_blocks, vault_root=None, parent=None)` — Task 5 def, Task 6 call (`_open_gear_dialog`) match.
- `_collect_all_blocks()` returns `list[tuple[str, str, _BlockNode]]` — Task 1 def, Task 6 consumer match.
- `save_to_node()` method on each section — Task 5 `accept()` calls all three.
- `_gear_btn` / `_add_child_btn` / `_all_rows_for_test` — Task 6 def, Task 6 tests consume.
