"""Hierarchical slot tree widget for the CSM template editor.

Tree layout (up to 3 levels):
    1   ▶  [资料库目录 ComboBox ────────]  ≡  ↓  ↑  🗑
      1-1 ▶  [资料库目录 ComboBox ──────]  ≡  ↓  ↑  🗑
        1-1-1 ▶  [资料库目录 ComboBox ──]  ≡  ↓  ↑  🗑
    2   ▶  [资料库目录 ComboBox ────────]  ≡  ↓  ↑  🗑

Key design decisions:
- Slot IDs are auto-generated from position on save: slot_1, slot_1_1, slot_1_1_2 …
- Source type is always 'notes_query'; directory ComboBox sets the module path.
- Detailed config (filter, pick_notes, depends_on) via ≡ context menu → small dialogs.
- depends_on stores positional IDs (slot_1_1); regenerated on rebuild.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
)

try:
    from qfluentwidgets import CaptionLabel
except ImportError:
    from qfluentwidgets import BodyLabel as CaptionLabel  # type: ignore

from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, SubtitleLabel,
    LineEdit, SpinBox, ComboBox,
    CardWidget, ScrollArea,
    TransparentToolButton, FluentIcon,
    InfoBar, InfoBarPosition,
    RoundMenu, Action,
    MessageBoxBase, SubtitleLabel,
)

try:
    from qfluentwidgets import CheckBox
except ImportError:
    from PyQt6.QtWidgets import QCheckBox as CheckBox  # type: ignore

from csm_core.template.schema import Slot, NotesQuerySource, PickCountSpec

# Reuse vault-scanning helpers from slot_editor_dialog
from .slot_editor_dialog import _scan_vault_dirs, _scan_frontmatter
from .cascade_picker import CascadePickerButton

_MAX_DEPTH = 3   # 1 = root only, 2 = root+child, 3 = root+child+grandchild

# ── Internal tree node ────────────────────────────────────────────────────────

@dataclass
class _TreeNode:
    """Pure-Python in-memory slot node (no Qt widgets)."""
    label: str = ""
    module: str = ""                              # vault relative path
    filter_cond: dict = field(default_factory=dict)
    pick_notes: object = 1                        # int | dict
    pick_variants: int = 1
    unique_notes: bool = False
    depends_on: list[str] = field(default_factory=list)  # positional IDs
    children: list["_TreeNode"] = field(default_factory=list)
    expanded: bool = False

    @classmethod
    def from_slot(cls, s: Slot) -> "_TreeNode":
        module = getattr(s.source, "module", "")
        filt: dict = {}
        if hasattr(s.source, "filter") and isinstance(s.source.filter, dict):
            filt = s.source.filter
        pick = s.pick_notes
        if hasattr(pick, "model_dump"):
            pick = pick.model_dump()
        unique = "unique_notes" in (s.constraints or [])
        raw_children = getattr(s, "children", None) or []
        return cls(
            label=s.label,
            module=module,
            filter_cond=filt,
            pick_notes=pick,
            pick_variants=s.pick_variants_per_note,
            unique_notes=unique,
            depends_on=list(s.depends_on or []),
            children=[cls.from_slot(c) for c in raw_children],
            expanded=bool(raw_children),
        )

    def to_slot(self, sid: str) -> Slot:
        """Serialize *this node only* — children are emitted separately by
        ``SlotTreeWidget.get_slots`` as siblings in the flat list. Keeping
        ``Slot`` schema flat (no nesting) means the assembler and render
        code don't need to know about the UI tree at all: each sub-variant
        becomes an independent slot that the sampler handles on its own,
        which is exactly what users expect when they add a 子变体.
        """
        source = NotesQuerySource(module=self.module, filter=self.filter_cond)
        if isinstance(self.pick_notes, int):
            pick: object = self.pick_notes
        else:
            pick = PickCountSpec.model_validate(self.pick_notes)
        constraints = ["unique_notes"] if self.unique_notes else []
        return Slot(
            id=sid,
            label=self.label or sid,
            source=source,
            pick_notes=pick,
            pick_variants_per_note=self.pick_variants,
            constraints=constraints,
            depends_on=self.depends_on,
        )


def _pos_from_indices(*indices: int) -> str:
    """(0, 1, 2) → '1-2-3'  (1-based display)"""
    return "-".join(str(i + 1) for i in indices)


def _id_from_pos(pos: str) -> str:
    """'1-2-3' → 'slot_1_2_3'"""
    return "slot_" + pos.replace("-", "_")


def _all_pos_nodes(
    nodes: list[_TreeNode], parent: str = ""
) -> list[tuple[str, _TreeNode]]:
    """Return [(pos, node), ...] depth-first for ALL nodes."""
    result: list[tuple[str, _TreeNode]] = []
    for i, n in enumerate(nodes):
        pos = f"{parent}-{i + 1}" if parent else str(i + 1)
        result.append((pos, n))
        result.extend(_all_pos_nodes(n.children, pos))
    return result


# ── Config dialogs (opened from ≡ menu) ──────────────────────────────────────

class _FilterDialog(MessageBoxBase):
    """Configure a slot's filter condition."""

    def __init__(self, node: _TreeNode, vault_root: Path | None, parent=None):
        super().__init__(parent)
        self._vault_root = vault_root
        self._fm: dict[str, list[str]] = {}

        self.titleLabel = SubtitleLabel("配置筛选条件", self)
        self.viewLayout.addWidget(self.titleLabel)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(BodyLabel("筛选条件（填写资料库笔记 frontmatter 属性，留空则不筛选）"))
        self.filter_edit = LineEdit(w)
        self.filter_edit.setPlaceholderText('如：{"组件类型":"痛点共鸣"}')
        if node.filter_cond:
            self.filter_edit.setText(json.dumps(node.filter_cond, ensure_ascii=False))
        lay.addWidget(self.filter_edit)

        hint_row = QHBoxLayout()
        hint_row.addWidget(BodyLabel("快捷填入（从资料库笔记属性中选择）"))
        hint_row.addStretch(1)
        self._refresh_hint = CaptionLabel("", w)
        hint_row.addWidget(self._refresh_hint)
        lay.addLayout(hint_row)

        hr = QHBoxLayout()
        self._key_combo = ComboBox(w)
        hr.addWidget(self._key_combo, 1)
        hr.addWidget(CaptionLabel(" = "))
        self._val_combo = ComboBox(w)
        hr.addWidget(self._val_combo, 1)
        apply_btn = TransparentToolButton(FluentIcon.ACCEPT_MEDIUM, w)
        apply_btn.setToolTip("写入筛选条件")
        apply_btn.clicked.connect(self._apply_quick)
        hr.addWidget(apply_btn)
        clear_btn = TransparentToolButton(FluentIcon.DELETE, w)
        clear_btn.setToolTip("清空")
        clear_btn.clicked.connect(lambda: self.filter_edit.clear())
        hr.addWidget(clear_btn)
        lay.addLayout(hr)

        self.viewLayout.addWidget(w)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

        self._key_combo.currentIndexChanged.connect(self._on_key_changed)
        self._load_frontmatter(vault_root, node.module)

    def _load_frontmatter(self, vault_root: Path | None, module: str) -> None:
        """Scan vault/module for frontmatter keys and populate key combo."""
        self._fm = {}
        self._key_combo.clear()
        self._val_combo.clear()

        if not vault_root or not module:
            self._refresh_hint.setText("（未设置资料库路径或模块）")
            return

        md_dir = vault_root / module
        if not md_dir.is_dir():
            self._refresh_hint.setText(f"（目录不存在: {module}）")
            return

        self._fm = _scan_frontmatter(md_dir)
        if not self._fm:
            self._refresh_hint.setText("（该目录暂无 frontmatter 属性）")
            return

        self._refresh_hint.setText("")
        self._key_combo.addItems(list(self._fm.keys()))
        # qfluentwidgets ComboBox 在 addItems 后不一定触发 currentIndexChanged
        # 需要显式填充 val combo
        if self._key_combo.count() > 0:
            first_key = self._key_combo.itemText(0)
            self._val_combo.addItems(self._fm.get(first_key, []))

    def _on_key_changed(self, _: int) -> None:
        key = self._key_combo.currentText()
        self._val_combo.clear()
        if key in self._fm:
            self._val_combo.addItems(self._fm[key])

    def _apply_quick(self) -> None:
        k = self._key_combo.currentText().strip()
        v = self._val_combo.currentText().strip()
        if k and v:
            self.filter_edit.setText(json.dumps({k: v}, ensure_ascii=False))

    def get_filter(self) -> dict:
        raw = self.filter_edit.text().strip()
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}


class _PickDialog(MessageBoxBase):
    """Configure pick_notes, pick_variants_per_note, unique_notes."""

    def __init__(self, node: _TreeNode, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("配置随机方式", self)
        self.viewLayout.addWidget(self.titleLabel)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(BodyLabel("采样模式"))
        self.mode_combo = ComboBox(w)
        self.mode_combo.addItems(["固定随机数量", "随机数量范围", "用户可配置"])
        lay.addWidget(self.mode_combo)

        self.stack = QStackedWidget(w)

        # Fixed
        fw = QWidget()
        fl = QHBoxLayout(fw)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(BodyLabel("数量："))
        self.fixed_spin = SpinBox(fw)
        self.fixed_spin.setRange(1, 20)
        self.fixed_spin.setValue(1)
        fl.addWidget(self.fixed_spin)
        fl.addStretch(1)
        self.stack.addWidget(fw)

        # Random
        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(BodyLabel("最小："))
        self.rnd_min = SpinBox(rw)
        self.rnd_min.setRange(1, 20)
        self.rnd_min.setValue(1)
        rl.addWidget(self.rnd_min)
        rl.addWidget(BodyLabel("  最大："))
        self.rnd_max = SpinBox(rw)
        self.rnd_max.setRange(1, 20)
        self.rnd_max.setValue(3)
        rl.addWidget(self.rnd_max)
        rl.addStretch(1)
        self.stack.addWidget(rw)

        # User-configurable
        uw = QWidget()
        ul = QHBoxLayout(uw)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.addWidget(BodyLabel("默认："))
        self.uc_default = SpinBox(uw)
        self.uc_default.setRange(1, 20)
        self.uc_default.setValue(2)
        ul.addWidget(self.uc_default)
        ul.addWidget(BodyLabel("  范围："))
        self.uc_min = SpinBox(uw)
        self.uc_min.setRange(1, 20)
        self.uc_min.setValue(1)
        ul.addWidget(self.uc_min)
        ul.addWidget(BodyLabel(" ~ "))
        self.uc_max = SpinBox(uw)
        self.uc_max.setRange(1, 20)
        self.uc_max.setValue(5)
        ul.addWidget(self.uc_max)
        ul.addStretch(1)
        self.stack.addWidget(uw)

        lay.addWidget(self.stack)
        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)

        lay.addWidget(BodyLabel("每篇笔记的变体数量"))
        self.variants_spin = SpinBox(w)
        self.variants_spin.setRange(1, 10)
        self.variants_spin.setValue(1)
        lay.addWidget(self.variants_spin)

        self.unique_cb = CheckBox("相同笔记不重复抽取", w)
        lay.addWidget(self.unique_cb)

        self.viewLayout.addWidget(w)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self._fill(node)

    def _fill(self, node: _TreeNode) -> None:
        pick = node.pick_notes
        if isinstance(pick, int):
            self.mode_combo.setCurrentIndex(0)
            self.stack.setCurrentIndex(0)
            self.fixed_spin.setValue(pick)
        elif isinstance(pick, dict):
            if "random_between" in pick:
                self.mode_combo.setCurrentIndex(1)
                self.stack.setCurrentIndex(1)
                rb = pick["random_between"] or []
                self.rnd_min.setValue(rb[0] if len(rb) > 0 else 1)
                self.rnd_max.setValue(rb[1] if len(rb) > 1 else 3)
            elif pick.get("user_configurable"):
                self.mode_combo.setCurrentIndex(2)
                self.stack.setCurrentIndex(2)
                self.uc_default.setValue(pick.get("default", 2))
                r = pick.get("range") or []
                self.uc_min.setValue(r[0] if len(r) > 0 else 1)
                self.uc_max.setValue(r[1] if len(r) > 1 else 5)
        self.variants_spin.setValue(node.pick_variants)
        self.unique_cb.setChecked(node.unique_notes)

    def get_pick_notes(self) -> object:
        mode = self.mode_combo.currentIndex()
        if mode == 0:
            return self.fixed_spin.value()
        elif mode == 1:
            return {"random_between": [self.rnd_min.value(), self.rnd_max.value()]}
        else:
            return {
                "user_configurable": True,
                "default": self.uc_default.value(),
                "range": [self.uc_min.value(), self.uc_max.value()],
            }

    def get_variants(self) -> int:
        return self.variants_spin.value()

    def get_unique(self) -> bool:
        return self.unique_cb.isChecked()


class _DependsDialog(MessageBoxBase):
    """Select which slots this slot depends on."""

    def __init__(
        self,
        current_deps: list[str],
        all_items: list[tuple[str, str, str]],  # (slot_id, pos, label)
        parent=None,
    ):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("设置跟随模块", self)
        self.viewLayout.addWidget(self.titleLabel)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(BodyLabel("勾选需要跟随模块"))

        self._checkboxes: list[tuple[str, CheckBox]] = []
        if all_items:
            for sid, pos, label in all_items:
                text = f"{pos}  {label}" if label else pos
                cb = CheckBox(text, w)
                cb.setChecked(sid in current_deps)
                lay.addWidget(cb)
                self._checkboxes.append((sid, cb))
        else:
            lay.addWidget(CaptionLabel("暂无其他模块可跟随"))

        self.viewLayout.addWidget(w)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

    def get_depends_on(self) -> list[str]:
        return [sid for sid, cb in self._checkboxes if cb.isChecked()]


# ── Slot row widget ───────────────────────────────────────────────────────────

class _SlotNodeRow(CardWidget):
    """One visual row:  [pos] [▶/▼] [ComboBox ─────────] [≡] [↓] [↑] [🗑]"""

    expand_toggled = pyqtSignal()
    move_up        = pyqtSignal()
    move_down      = pyqtSignal()
    delete_req     = pyqtSignal()
    module_changed = pyqtSignal(str)
    label_changed  = pyqtSignal()
    menu_req       = pyqtSignal()

    _INDENT_PX = 28  # pixels per nesting level

    def __init__(
        self,
        node: _TreeNode,
        position: str,
        level: int,
        vault_dirs: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self._node = node
        self._vault_dirs = vault_dirs

        h = QHBoxLayout(self)
        h.setContentsMargins(16 + level * self._INDENT_PX, 10, 12, 10)
        h.setSpacing(8)

        # ── Position label ────────────────────────────────────────────────
        pos_lbl = SubtitleLabel(position)
        pos_lbl.setFixedWidth(max(32, 14 * len(position)))
        pos_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(pos_lbl)

        # ── Expand / collapse ─────────────────────────────────────────────
        self._expand_btn = TransparentToolButton(FluentIcon.CHEVRON_RIGHT, self)
        self._expand_btn.setFixedSize(26, 26)
        self._expand_btn.clicked.connect(self.expand_toggled)
        h.addWidget(self._expand_btn)

        # ── Cascading module picker ───────────────────────────────────────
        self._picker = CascadePickerButton(self)
        self._picker.setup(vault_dirs, node.module)
        self._picker.path_selected.connect(self._on_module_selected)
        h.addWidget(self._picker)

        # ── Display-name editor ───────────────────────────────────────────
        # Users can type a custom paragraph name here; this label is what the
        # article page shows next to the slot card (instead of the raw
        # ``slot_6_1`` ID) and what downstream exports use. Falls back to the
        # module basename if left blank.
        self._label_edit = LineEdit(self)
        self._label_edit.setPlaceholderText("段落名称（可选）")
        self._label_edit.setText(node.label or "")
        self._label_edit.setMaximumWidth(180)
        self._label_edit.editingFinished.connect(self._on_label_edited)
        h.addWidget(self._label_edit)

        h.addStretch(1)

        # ── Action buttons ────────────────────────────────────────────────
        for icon, sig in [
            (FluentIcon.MORE,   self.menu_req),
            (FluentIcon.DOWN,   self.move_down),
            (FluentIcon.UP,     self.move_up),
            (FluentIcon.DELETE, self.delete_req),
        ]:
            btn = TransparentToolButton(icon, self)
            btn.setFixedSize(28, 28)
            btn.clicked.connect(sig)
            h.addWidget(btn)

        self._update_expand_icon()

    def _on_module_selected(self, path: str) -> None:
        old_basename = Path(self._node.module).name if self._node.module else ""
        self._node.module = path
        # Auto-fill the label with the new directory basename *only* when the
        # user hasn't customised it — either blank or still equal to the
        # previous directory's basename (meaning it was auto-filled before).
        if not self._node.label or self._node.label == old_basename:
            self._node.label = Path(path).name
            self._label_edit.setText(self._node.label)
        self.module_changed.emit(path)

    def _on_label_edited(self) -> None:
        new_label = self._label_edit.text().strip()
        if new_label != self._node.label:
            self._node.label = new_label
            self.label_changed.emit()

    def _update_expand_icon(self) -> None:
        has_children = bool(self._node.children)
        self._expand_btn.setVisible(has_children)
        if has_children and self._node.expanded:
            self._expand_btn.setIcon(FluentIcon.CHEVRON_DOWN_MED)
        else:
            self._expand_btn.setIcon(FluentIcon.CHEVRON_RIGHT)

    def refresh_icon(self) -> None:
        self._update_expand_icon()


# ── Main tree widget ──────────────────────────────────────────────────────────

class SlotTreeWidget(QWidget):
    """Hierarchical slot list (up to _MAX_DEPTH levels).

    Public API mirrors the old _SlotsPage:
        load_slots(slots)  — populate from list[Slot]
        get_slots()        — return list[Slot] (top-level, children nested inside)
        set_vault_root(p)  — update vault path
        add_root_slot()    — append new empty top-level slot

    Signal:
        slots_changed      — emitted on any structural or data change
    """

    slots_changed = pyqtSignal()

    def __init__(self, vault_root: Path | None = None, parent=None):
        super().__init__(parent)
        self._vault_root: Path | None = vault_root
        self._vault_dirs: list[str] = _scan_vault_dirs(vault_root) if vault_root else []
        self._roots: list[_TreeNode] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea, #sw {background: transparent; border: none;}"
        )
        self._inner = QWidget()
        self._inner.setObjectName("sw")
        self._scroll.setWidget(self._inner)

        self._lo = QVBoxLayout(self._inner)
        self._lo.setContentsMargins(0, 4, 0, 8)
        self._lo.setSpacing(8)
        self._lo.addStretch(1)  # trailing stretch — always last

        outer.addWidget(self._scroll, 1)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_vault_root(self, path: Path | None) -> None:
        self._vault_root = path
        self._vault_dirs = _scan_vault_dirs(path) if path else []
        self._rebuild()

    def load_slots(self, slots: list[Slot]) -> None:
        """Rebuild the tree from a flat slot list.

        Sub-variants are persisted as siblings with positional IDs
        (``slot_6``, ``slot_6_1``, ``slot_6_2`` …). The parent-child
        relationship is recovered from the ID suffix: ``slot_6_1``'s parent
        is whichever slot has id ``slot_6``. Slots must appear in
        depth-first order (parent before its descendants) — which is how
        ``get_slots`` writes them — so a single pass is enough.
        """
        self._roots = []
        nodes_by_id: dict[str, _TreeNode] = {}
        for s in slots:
            node = _TreeNode.from_slot(s)
            nodes_by_id[s.id] = node
            parts = s.id.split("_")
            if len(parts) <= 2:
                # "slot_6" — top level
                self._roots.append(node)
                continue
            parent_id = "_".join(parts[:-1])
            parent = nodes_by_id.get(parent_id)
            if parent is None:
                # Orphaned child (malformed template): promote to root so
                # the user can still see and fix it rather than losing it.
                self._roots.append(node)
            else:
                parent.children.append(node)
                parent.expanded = True
        self._rebuild()

    def get_slots(self) -> list[Slot]:
        """Return a *flat* depth-first list of Slots with positional IDs.

        Each _TreeNode (parent or child) becomes its own Slot. The assembler
        samples them independently, so a parent with N children produces
        1 + N picks in the draft — the user sees the parent's content
        followed by each sub-variant's content, in order.
        """
        out: list[Slot] = []

        def walk(node: _TreeNode, sid: str) -> None:
            out.append(node.to_slot(sid))
            for j, child in enumerate(node.children):
                walk(child, f"{sid}_{j + 1}")

        for i, n in enumerate(self._roots):
            walk(n, f"slot_{i + 1}")
        return out

    def add_root_slot(self) -> None:
        self._roots.append(_TreeNode())
        self._rebuild()
        self.slots_changed.emit()

    # ── Internal rebuild ──────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        # Remove all rows (keep trailing stretch at index lo.count()-1)
        while self._lo.count() > 1:
            item = self._lo.takeAt(0)
            if (w := item.widget()):
                w.setParent(None)
                w.deleteLater()
        self._render_nodes(self._roots, parent_pos="", level=0)

    def _render_nodes(
        self, nodes: list[_TreeNode], parent_pos: str, level: int
    ) -> None:
        for i, node in enumerate(nodes):
            pos = f"{parent_pos}-{i + 1}" if parent_pos else str(i + 1)
            row = _SlotNodeRow(node, pos, level, self._vault_dirs, self._inner)

            # Connect row signals (use default-arg capture to avoid closure issues)
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
            row.module_changed.connect(
                lambda _path, _rebuild=True: (
                    self._rebuild(), self.slots_changed.emit()
                )
            )
            row.label_changed.connect(self.slots_changed.emit)
            row.menu_req.connect(
                lambda _n=node, _row=row, _lv=level: self._show_menu(_n, _row, _lv)
            )

            self._lo.insertWidget(self._lo.count() - 1, row)

            # Recursively render children if expanded
            if node.expanded and node.children:
                self._render_nodes(node.children, pos, level + 1)

    # ── Node operations ───────────────────────────────────────────────────────

    def _on_toggle(self, node: _TreeNode) -> None:
        node.expanded = not node.expanded
        self._rebuild()

    def _move_node(self, siblings: list[_TreeNode], idx: int, delta: int) -> None:
        tgt = idx + delta
        if 0 <= tgt < len(siblings):
            siblings[idx], siblings[tgt] = siblings[tgt], siblings[idx]
            self._rebuild()
            self.slots_changed.emit()

    def _delete_node(self, siblings: list[_TreeNode], idx: int) -> None:
        siblings.pop(idx)
        # Defer rebuild so we exit the row's signal call stack before
        # the row widget itself is destroyed by _rebuild().
        QTimer.singleShot(0, self._rebuild_and_emit)

    def _delete_by_ref(self, target: _TreeNode) -> None:
        def _remove(nodes: list[_TreeNode]) -> bool:
            for i, n in enumerate(nodes):
                if n is target:
                    nodes.pop(i)
                    return True
                if _remove(n.children):
                    return True
            return False
        _remove(self._roots)
        QTimer.singleShot(0, self._rebuild_and_emit)

    def _rebuild_and_emit(self) -> None:
        self._rebuild()
        self.slots_changed.emit()

    def _add_child(self, parent: _TreeNode) -> None:
        # Seed the new child with the parent's module / filter / pick
        # configuration. Users almost always want a sub-variant to sample
        # from the same folder (otherwise they'd add a top-level slot);
        # starting blank forced them to re-pick the folder every time.
        # Default label = "<parent label> - 变体N" so the article page shows
        # something meaningful instead of the raw ``slot_x_y`` ID.
        base_label = parent.label or Path(parent.module).name or "段落"
        child_label = f"{base_label} - 变体{len(parent.children) + 1}"
        child = _TreeNode(
            label=child_label,
            module=parent.module,
            filter_cond=dict(parent.filter_cond),
            pick_notes=(
                dict(parent.pick_notes)
                if isinstance(parent.pick_notes, dict)
                else parent.pick_notes
            ),
            pick_variants=parent.pick_variants,
            unique_notes=parent.unique_notes,
        )
        parent.children.append(child)
        parent.expanded = True
        self._rebuild()
        self.slots_changed.emit()

    # ── ≡ Context menu ────────────────────────────────────────────────────────

    def _show_menu(self, node: _TreeNode, row: _SlotNodeRow, level: int) -> None:
        menu = RoundMenu(parent=row)

        # Add child variant (only if not at max depth)
        if level < _MAX_DEPTH - 1:
            act_add = Action(FluentIcon.ADD, "添加子变体")
            act_add.triggered.connect(lambda: self._add_child(node))
            menu.addAction(act_add)
            menu.addSeparator()

        # Configuration actions
        act_filter = Action(FluentIcon.FILTER, "配置筛选条件…")
        act_filter.triggered.connect(
            lambda: self._configure_filter(node, row)
        )
        menu.addAction(act_filter)

        act_pick = Action(FluentIcon.SETTING, "配置随机方式…")
        act_pick.triggered.connect(lambda: self._configure_pick(node, row))
        menu.addAction(act_pick)

        act_dep = Action(FluentIcon.LINK, "设置跟随模块…")
        act_dep.triggered.connect(lambda: self._configure_depends(node, row))
        menu.addAction(act_dep)

        menu.addSeparator()

        act_del = Action(FluentIcon.DELETE, "删除此模块")
        act_del.triggered.connect(lambda: self._delete_by_ref(node))
        menu.addAction(act_del)

        menu.exec(QCursor.pos())

    # ── Dialog launchers ──────────────────────────────────────────────────────

    def _configure_filter(self, node: _TreeNode, row: _SlotNodeRow) -> None:
        dlg = _FilterDialog(node, self._vault_root, parent=self.window())
        if dlg.exec():
            node.filter_cond = dlg.get_filter()
            self.slots_changed.emit()

    def _configure_pick(self, node: _TreeNode, row: _SlotNodeRow) -> None:
        dlg = _PickDialog(node, parent=self.window())
        if dlg.exec():
            node.pick_notes = dlg.get_pick_notes()
            node.pick_variants = dlg.get_variants()
            node.unique_notes = dlg.get_unique()
            self.slots_changed.emit()

    def _configure_depends(self, node: _TreeNode, row: _SlotNodeRow) -> None:
        # Build all-positions list (excluding self)
        all_items: list[tuple[str, str, str]] = []
        for pos, n in _all_pos_nodes(self._roots):
            if n is not node:
                sid = _id_from_pos(pos)
                all_items.append((sid, pos, n.label))

        dlg = _DependsDialog(node.depends_on, all_items, parent=self.window())
        if dlg.exec():
            node.depends_on = dlg.get_depends_on()
            self.slots_changed.emit()
