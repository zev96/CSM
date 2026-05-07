"""Compact block list — left column of the template editor.

One row per top-level block with: index circle, kind chip, name + 1-line
desc, optional skill chip, gear (高级) and × (delete). Click a row to
select; drag-handle is a visual placeholder (no DnD yet — use ↑↓ on
inspector or the existing add/delete flow).

Mutates ``_BlockNode`` instances in place; emits signals after structural
changes so the editor can refresh inspector + dirty state.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
)

from qfluentwidgets import (
    TransparentToolButton, FluentIcon, ScrollArea,
)

from csm_core.template.schema import Block
from .slot_tree_widget import _BlockNode, _scan_vault_dirs


# ── Tokens ────────────────────────────────────────────────────────────────────
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_4  = "rgba(30,28,25,0.18)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT       = "#2f6f5e"
_ACCENT_SOFTER= "#ecf2ee"
_SURFACE = "#ffffff"


_KIND_LABELS = {
    "paragraph":      "段落",
    "heading":        "标题",
    "numbered_list":  "编号列表",
    "hero_brand":     "主推",
    "competitor_pool":"对比池",
    "literal":        "文本",
    "test_framework": "测试部分",
}


def _node_display_name(node: _BlockNode, fallback: str) -> str:
    if node.kind == "heading":
        return node.text or fallback
    if node.kind == "hero_brand":
        return node.title or fallback
    if node.kind == "literal":
        return (node.literal_text or fallback).splitlines()[0][:32]
    return node.label or fallback


def _node_desc(node: _BlockNode) -> str:
    if node.kind == "heading":
        idx = node.index or "—"
        return f"H{node.level} · 序号 {idx}"
    if node.kind == "hero_brand":
        return f"主推卡片 · {node.reason_label or '推荐理由'}"
    if node.kind == "literal":
        text = (node.literal_text or "").replace("\n", " ")
        return text[:48] or "（空文本）"
    if node.kind == "paragraph":
        mod = node.module or "未选目录"
        return f"目录：{mod}"
    if node.kind == "numbered_list":
        mod = node.module or "未选目录"
        return f"目录：{mod} · 样式 {node.number_style}"
    if node.kind == "competitor_pool":
        mod = node.module or "未选目录"
        return f"竞品池 · 目录：{mod}"
    return "—"


# ── Single row ────────────────────────────────────────────────────────────────
class _BlockRow(QFrame):
    clicked        = pyqtSignal()
    move_up        = pyqtSignal()
    move_down      = pyqtSignal()

    def __init__(self, idx: int, node: _BlockNode, *, selected: bool = False, parent=None):
        super().__init__(parent)
        self._node = node
        self._selected = selected
        self.setObjectName("BlockRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)
        self._apply_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(10)

        # Drag-handle visual (not active)
        grip = QLabel("⋮⋮", self)
        grip.setStyleSheet(
            f"color: {_INK_3}; font-size: 11px; background: transparent;"
            "font-family: Consolas, monospace;")
        grip.setFixedWidth(12)
        lay.addWidget(grip)

        # Index circle
        idx_lbl = QLabel(str(idx + 1), self)
        idx_lbl.setFixedSize(26, 26)
        idx_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idx_lbl.setStyleSheet(
            f"background: {_INK_5}; color: {_INK};"
            "font-size: 11px; font-weight: 600; border-radius: 6px;")
        lay.addWidget(idx_lbl)

        # Name + desc column
        col = QVBoxLayout(); col.setSpacing(2); col.setContentsMargins(0, 0, 0, 0)
        name = QLabel(_node_display_name(node, _KIND_LABELS.get(node.kind, "区块")), self)
        name.setStyleSheet(
            f"color: {_INK}; font-size: 13.5px; font-weight: 600;"
            "background: transparent; border: none;")
        name.setWordWrap(False)
        col.addWidget(name)
        desc = QLabel(_node_desc(node), self)
        desc.setStyleSheet(
            f"color: {_INK_2}; font-size: 11.5px;"
            "background: transparent; border: none;")
        desc.setWordWrap(False)
        col.addWidget(desc)
        lay.addLayout(col, 1)

        # Kind chip
        chip = QLabel(_KIND_LABELS.get(node.kind, node.kind), self)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setStyleSheet(
            f"padding: 3px 10px; border-radius: 999px;"
            f"border: 1px solid {_INK_4}; background: transparent;"
            f"color: {_INK_2}; font-size: 11px;")
        chip.setFixedHeight(22)
        lay.addWidget(chip)

        # Move (delete moved to right inspector)
        small_icon = QSize(12, 12)
        up_btn = TransparentToolButton(FluentIcon.UP, self)
        up_btn.setFixedSize(20, 20)
        up_btn.setIconSize(small_icon)
        up_btn.clicked.connect(lambda: self.move_up.emit())
        lay.addWidget(up_btn)
        down_btn = TransparentToolButton(FluentIcon.DOWN, self)
        down_btn.setFixedSize(20, 20)
        down_btn.setIconSize(small_icon)
        down_btn.clicked.connect(lambda: self.move_down.emit())
        lay.addWidget(down_btn)

    # ── Visual state ──────────────────────────────────────────────────────
    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"#BlockRow {{ background: {_SURFACE};"
                f" border: 1.5px solid {_ACCENT}; border-radius: 12px; }}"
            )
        else:
            self.setStyleSheet(
                f"#BlockRow {{ background: {_SURFACE};"
                f" border: 1.5px solid {_INK_5}; border-radius: 12px; }}"
                f"#BlockRow:hover {{ border-color: {_INK_4}; }}"
            )

    def set_selected(self, sel: bool) -> None:
        self._selected = sel
        self._apply_style()

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ── List widget ───────────────────────────────────────────────────────────────
class BlockListWidget(QWidget):
    """Top-level (flat) block list. Children of paragraph blocks are not
    shown here — manage them via the inspector's 高级 dialog."""

    block_selected = pyqtSignal(int)
    blocks_changed = pyqtSignal()

    def __init__(self, vault_root: Path | None = None, parent=None):
        super().__init__(parent)
        self._vault_root: Path | None = vault_root
        self._vault_dirs: list[str] = _scan_vault_dirs(vault_root) if vault_root else []
        self._roots: list[_BlockNode] = []
        self._rows: list[_BlockRow] = []
        self._selected_idx: int = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "ScrollArea, QScrollArea, QScrollArea > QWidget > QWidget {"
            " background: transparent; border: none; }")
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._inner)
        self._lo = QVBoxLayout(self._inner)
        # Right padding pushes rows away from the scrollbar.
        self._lo.setContentsMargins(0, 4, 18, 8)
        self._lo.setSpacing(8)
        self._lo.addStretch(1)
        outer.addWidget(self._scroll, 1)

    # ── Public API ────────────────────────────────────────────────────────
    def set_vault_root(self, path: Path | None) -> None:
        self._vault_root = path
        self._vault_dirs = _scan_vault_dirs(path) if path else []

    def vault_root(self) -> Path | None:
        return self._vault_root

    def vault_dirs(self) -> list[str]:
        return list(self._vault_dirs)

    def load_blocks(self, blocks: list[Block]) -> None:
        self._roots = [_BlockNode.from_block(b) for b in blocks]
        self._selected_idx = 0 if self._roots else -1
        self._rebuild()
        if self._selected_idx >= 0:
            self.block_selected.emit(self._selected_idx)

    def get_blocks(self) -> list[Block]:
        return [n.to_block(f"block_{i + 1}") for i, n in enumerate(self._roots)]

    def add_root_block(self, kind: str = "paragraph") -> None:
        self._roots.append(_BlockNode(kind=kind))
        self._selected_idx = len(self._roots) - 1
        self._rebuild()
        self.blocks_changed.emit()
        self.block_selected.emit(self._selected_idx)

    def selected_index(self) -> int:
        return self._selected_idx

    def current_node(self) -> _BlockNode | None:
        if 0 <= self._selected_idx < len(self._roots):
            return self._roots[self._selected_idx]
        return None

    def total(self) -> int:
        return len(self._roots)

    def refresh_current_row(self) -> None:
        """After inspector edits a node, repaint just the affected row."""
        if not (0 <= self._selected_idx < len(self._rows)):
            return
        # Cheap path: full rebuild keeps things consistent at minor cost.
        self._rebuild()

    def select(self, idx: int) -> None:
        if not (0 <= idx < len(self._roots)):
            return
        self._selected_idx = idx
        for i, r in enumerate(self._rows):
            r.set_selected(i == idx)
        self.block_selected.emit(idx)

    # ── Internal ──────────────────────────────────────────────────────────
    def _rebuild(self) -> None:
        # Remove existing rows.
        while self._lo.count() > 1:
            item = self._lo.takeAt(0)
            if (w := item.widget()):
                w.setParent(None)
                w.deleteLater()
        self._rows = []
        for i, node in enumerate(self._roots):
            row = _BlockRow(i, node, selected=(i == self._selected_idx),
                            parent=self._inner)
            row.clicked.connect(lambda _i=i: self.select(_i))
            row.move_up.connect(lambda _i=i: self._move(_i, -1))
            row.move_down.connect(lambda _i=i: self._move(_i, +1))
            self._lo.insertWidget(self._lo.count() - 1, row)
            self._rows.append(row)

    def _move(self, idx: int, delta: int) -> None:
        tgt = idx + delta
        if not (0 <= tgt < len(self._roots)):
            return
        self._roots[idx], self._roots[tgt] = self._roots[tgt], self._roots[idx]
        if self._selected_idx == idx:
            self._selected_idx = tgt
        elif self._selected_idx == tgt:
            self._selected_idx = idx
        self._rebuild()
        self.blocks_changed.emit()

    def _delete(self, idx: int) -> None:
        if not (0 <= idx < len(self._roots)):
            return
        self._roots.pop(idx)
        if not self._roots:
            self._selected_idx = -1
        else:
            self._selected_idx = min(self._selected_idx, len(self._roots) - 1)
        QTimer.singleShot(0, self._rebuild_and_emit)

    def _rebuild_and_emit(self) -> None:
        self._rebuild()
        self.blocks_changed.emit()
        self.block_selected.emit(self._selected_idx)

    def _open_gear(self, idx: int) -> None:
        if not (0 <= idx < len(self._roots)):
            return
        from .block_advanced_dialog import BlockAdvancedDialog
        node = self._roots[idx]
        all_blocks = [(f"block_{i + 1}", n.label or n.text or f"block_{i + 1}", n)
                      for i, n in enumerate(self._roots)]
        dlg = BlockAdvancedDialog(
            node=node,
            all_blocks=all_blocks,
            vault_root=self._vault_root,
            parent=self.window(),
        )
        if dlg.exec():
            self._rebuild()
            self.blocks_changed.emit()
