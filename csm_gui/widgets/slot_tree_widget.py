"""Hierarchical block tree widget for the CSM template editor.

Supports all 6 block kinds: paragraph, heading, numbered_list,
hero_brand, competitor_pool, literal.

Each row has:
  [pos] [kind ComboBox] [QStackedWidget with per-kind fields] [↓] [↑] [🗑]

Only paragraph blocks keep the children tree / expand chevron.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QSizePolicy,
)

try:
    from qfluentwidgets import CaptionLabel
except ImportError:
    from qfluentwidgets import BodyLabel as CaptionLabel  # type: ignore

from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, SubtitleLabel,
    LineEdit, SpinBox, ComboBox, TextEdit,
    CardWidget, ScrollArea,
    TransparentToolButton, FluentIcon,
    InfoBar, InfoBarPosition,
    RoundMenu, Action,
    MessageBoxBase,
)

try:
    from qfluentwidgets import CheckBox
except ImportError:
    from PyQt6.QtWidgets import QCheckBox as CheckBox  # type: ignore

from csm_core.template.schema import (
    Block,
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    NotesQuerySource, PickCountSpec,
)

from .cascade_picker import CascadePickerButton

_SKIP_DIRS = {
    ".obsidian", ".trash", ".git", "__pycache__",
    ".venv", "node_modules", ".system_generated",
}


def _scan_vault_dirs(vault_root: Path) -> list[str]:
    """Return sorted relative paths of leaf subdirs that directly contain .md files."""
    candidates: list[str] = []
    try:
        for p in sorted(vault_root.rglob("*")):
            if not p.is_dir():
                continue
            try:
                rel_parts = p.relative_to(vault_root).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts):
                continue
            if not any(c.suffix == ".md" for c in p.iterdir() if c.is_file()):
                continue
            candidates.append("/".join(rel_parts))
            if len(candidates) >= 300:
                break
    except Exception:
        pass
    cset = set(candidates)
    return sorted(
        d for d in candidates
        if not any(other.startswith(d + "/") for other in cset)
    )


def _scan_frontmatter(md_dir: Path) -> dict[str, list[str]]:
    """Return ``{key: sorted_unique_values}`` from YAML frontmatter of .md files."""
    seen: dict[str, set[str]] = {}
    try:
        for md in sorted(md_dir.glob("*.md"))[:200]:
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
                in_fm = started = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped == "---":
                        if not started:
                            started = in_fm = True
                            continue
                        break
                    if in_fm and ":" in stripped and not stripped.startswith("#"):
                        k, _, v = stripped.partition(":")
                        k, v = k.strip(), v.strip()
                        if k and v:
                            seen.setdefault(k, set()).add(v)
            except Exception:
                pass
    except Exception:
        pass
    return {k: sorted(vs) for k, vs in sorted(seen.items())}

_MAX_DEPTH = 3   # 1 = root only, 2 = root+child, 3 = root+child+grandchild

BLOCK_KINDS = [
    "paragraph",
    "heading",
    "numbered_list",
    "hero_brand",
    "competitor_pool",
    "literal",
]

BLOCK_KIND_LABELS = {
    "paragraph":       "段落",
    "heading":         "标题",
    "numbered_list":   "编号列表",
    "hero_brand":      "主推品",
    "competitor_pool": "竞品池",
    "literal":         "固定文本",
}

NUMBER_STYLE_OPTIONS = ["1.", "一、", "none"]


# ── Internal tree node ────────────────────────────────────────────────────────

@dataclass
class _BlockNode:
    """Pure-Python in-memory block node (no Qt widgets)."""
    kind: str = "paragraph"
    block_id: str = ""

    # --- paragraph / numbered_list / competitor_pool fields ---
    module: str = ""
    filter_cond: dict = field(default_factory=dict)
    pick_notes: object = 1          # int | dict
    # paragraph-only
    label: str = ""
    pick_variants: int = 1
    unique_notes: bool = False
    depends_on: list[str] = field(default_factory=list)
    children: list["_BlockNode"] = field(default_factory=list)
    expanded: bool = False

    # --- heading fields ---
    level: int = 2
    index: str = ""
    text: str = ""

    # --- numbered_list-only ---
    number_style: str = "1."

    # --- hero_brand fields ---
    title: str = ""
    reason_label: str = "推荐理由："

    # --- literal field ---
    literal_text: str = ""

    @classmethod
    def from_block(cls, b: Block) -> "_BlockNode":
        n = cls(kind=b.kind, block_id=b.id)
        if isinstance(b, ParagraphBlock):
            src = b.source
            n.module = getattr(src, "module", "")
            if hasattr(src, "filter") and isinstance(src.filter, dict):
                n.filter_cond = src.filter
            pick = b.pick_notes
            if hasattr(pick, "model_dump"):
                pick = pick.model_dump()
            n.pick_notes = pick
            n.label = b.label
            n.pick_variants = b.pick_variants_per_note
            n.unique_notes = "unique_notes" in (b.constraints or [])
            n.depends_on = list(b.depends_on or [])
            n.children = [cls.from_block(c) for c in (b.children or [])]
            n.expanded = bool(b.children)
        elif isinstance(b, HeadingBlock):
            n.level = b.level
            n.index = b.index
            n.text = b.text
        elif isinstance(b, NumberedListBlock):
            src = b.source
            n.module = getattr(src, "module", "")
            if hasattr(src, "filter") and isinstance(src.filter, dict):
                n.filter_cond = src.filter
            pick = b.pick_notes
            if hasattr(pick, "model_dump"):
                pick = pick.model_dump()
            n.pick_notes = pick
            n.label = b.label
            n.number_style = b.number_style
        elif isinstance(b, HeroBrandBlock):
            n.title = b.title
            n.reason_label = b.reason_label
            n.number_style = b.number_style
        elif isinstance(b, CompetitorPoolBlock):
            src = b.source
            n.module = getattr(src, "module", "")
            if hasattr(src, "filter") and isinstance(src.filter, dict):
                n.filter_cond = src.filter
            pick = b.pick_notes
            if hasattr(pick, "model_dump"):
                pick = pick.model_dump()
            n.pick_notes = pick
            n.reason_label = b.reason_label
        elif isinstance(b, LiteralBlock):
            n.literal_text = b.text
        return n

    def to_block(self, bid: str) -> Block:
        """Serialize this node to a Block pydantic object."""
        if self.kind == "paragraph":
            source = NotesQuerySource(module=self.module, filter=self.filter_cond)
            pick: Any = self._resolve_pick(self.pick_notes)
            constraints = ["unique_notes"] if self.unique_notes else []
            # Children become nested ParagraphBlock children
            children_blocks = []
            for j, child in enumerate(self.children):
                cb = child.to_block(f"{bid}_{j + 1}")
                if isinstance(cb, ParagraphBlock):
                    children_blocks.append(cb)
            return ParagraphBlock(
                id=bid,
                label=self.label or bid,
                source=source,
                pick_notes=pick,
                pick_variants_per_note=self.pick_variants,
                constraints=constraints,
                depends_on=self.depends_on,
                children=children_blocks,
            )
        elif self.kind == "heading":
            return HeadingBlock(
                id=bid,
                level=self.level,
                index=self.index,
                text=self.text or "标题",
            )
        elif self.kind == "numbered_list":
            source = NotesQuerySource(module=self.module, filter=self.filter_cond)
            pick = self._resolve_pick(self.pick_notes)
            return NumberedListBlock(
                id=bid,
                label=self.label or bid,
                source=source,
                pick_notes=pick,
                number_style=self.number_style,
            )
        elif self.kind == "hero_brand":
            return HeroBrandBlock(
                id=bid,
                title=self.title or "品牌",
                reason_label=self.reason_label or "推荐理由：",
                number_style=self.number_style,
            )
        elif self.kind == "competitor_pool":
            source = NotesQuerySource(module=self.module, filter=self.filter_cond)
            pick = self._resolve_pick(self.pick_notes)
            return CompetitorPoolBlock(
                id=bid,
                source=source,
                pick_notes=pick,
                reason_label=self.reason_label or "推荐理由：",
            )
        elif self.kind == "literal":
            return LiteralBlock(
                id=bid,
                text=self.literal_text or "文本",
            )
        else:
            raise ValueError(f"Unknown block kind: {self.kind!r}")

    @staticmethod
    def _resolve_pick(pick_notes: Any) -> Any:
        if isinstance(pick_notes, int):
            return pick_notes
        elif isinstance(pick_notes, dict):
            return PickCountSpec.model_validate(pick_notes)
        return pick_notes


def _pos_from_indices(*indices: int) -> str:
    return "-".join(str(i + 1) for i in indices)


def _id_from_pos(pos: str) -> str:
    return "block_" + pos.replace("-", "_")


def _all_pos_nodes(
    nodes: list[_BlockNode], parent: str = ""
) -> list[tuple[str, _BlockNode]]:
    result: list[tuple[str, _BlockNode]] = []
    for i, n in enumerate(nodes):
        pos = f"{parent}-{i + 1}" if parent else str(i + 1)
        result.append((pos, n))
        if n.kind == "paragraph":
            result.extend(_all_pos_nodes(n.children, pos))
    return result


# ── Per-kind field pages ──────────────────────────────────────────────────────

def _make_source_row(parent: QWidget) -> tuple[QWidget, CascadePickerButton, LineEdit]:
    """Returns (container, picker, label_edit)."""
    w = QWidget(parent)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(BodyLabel("目录："))
    picker = CascadePickerButton(w)
    picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    lay.addWidget(picker, 2)
    lay.addWidget(BodyLabel("名称："))
    label_edit = LineEdit(w)
    label_edit.setPlaceholderText("段落名称")
    label_edit.setMaximumWidth(160)
    lay.addWidget(label_edit, 1)
    return w, picker, label_edit



class _ParagraphPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, node: _BlockNode, vault_dirs: list[str], parent=None):
        super().__init__(parent)
        self._node = node
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        src_w, self._picker, self._label_edit = _make_source_row(self)
        self._picker.setup(vault_dirs, node.module)
        self._picker.path_selected.connect(self._on_module)
        self._label_edit.setText(node.label or "")
        self._label_edit.editingFinished.connect(self._on_label)
        lay.addWidget(src_w)

    def _on_module(self, path: str) -> None:
        old_basename = Path(self._node.module).name if self._node.module else ""
        self._node.module = path
        if not self._node.label or self._node.label == old_basename:
            self._node.label = Path(path).name
            self._label_edit.setText(self._node.label)
        self.changed.emit()

    def _on_label(self) -> None:
        new = self._label_edit.text().strip()
        if new != self._node.label:
            self._node.label = new
            self.changed.emit()

    def refresh(self, vault_dirs: list[str]) -> None:
        self._picker.setup(vault_dirs, self._node.module)


class _HeadingPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, node: _BlockNode, parent=None):
        super().__init__(parent)
        self._node = node
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(BodyLabel("级别："))
        self._level_spin = SpinBox(self)
        self._level_spin.setRange(1, 3)
        self._level_spin.setValue(node.level)
        self._level_spin.setMaximumWidth(70)
        self._level_spin.valueChanged.connect(self._on_level)
        lay.addWidget(self._level_spin)

        lay.addWidget(BodyLabel("序号："))
        self._index_edit = LineEdit(self)
        self._index_edit.setPlaceholderText("如：一")
        self._index_edit.setText(node.index)
        self._index_edit.setMaximumWidth(80)
        self._index_edit.editingFinished.connect(self._on_index)
        lay.addWidget(self._index_edit)

        lay.addWidget(BodyLabel("文本："))
        self._text_edit = LineEdit(self)
        self._text_edit.setPlaceholderText("标题文本")
        self._text_edit.setText(node.text)
        self._text_edit.editingFinished.connect(self._on_text)
        lay.addWidget(self._text_edit, 1)

    def _on_level(self, v: int) -> None:
        self._node.level = v
        self.changed.emit()

    def _on_index(self) -> None:
        self._node.index = self._index_edit.text().strip()
        self.changed.emit()

    def _on_text(self) -> None:
        self._node.text = self._text_edit.text().strip()
        self.changed.emit()


class _NumberedListPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, node: _BlockNode, vault_dirs: list[str], parent=None):
        super().__init__(parent)
        self._node = node
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        src_w = QWidget(self)
        src_lay = QHBoxLayout(src_w)
        src_lay.setContentsMargins(0, 0, 0, 0)
        src_lay.setSpacing(6)
        src_lay.addWidget(BodyLabel("目录："))
        self._picker = CascadePickerButton(src_w)
        self._picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._picker.setup(vault_dirs, node.module)
        self._picker.path_selected.connect(self._on_module)
        src_lay.addWidget(self._picker, 2)
        src_lay.addWidget(BodyLabel("名称："))
        self._label_edit = LineEdit(src_w)
        self._label_edit.setPlaceholderText("段落名称")
        self._label_edit.setMaximumWidth(160)
        self._label_edit.setText(node.label or "")
        self._label_edit.editingFinished.connect(self._on_label)
        src_lay.addWidget(self._label_edit, 1)
        src_lay.addWidget(BodyLabel("编号样式："))
        self._style_combo = ComboBox(src_w)
        self._style_combo.addItems(NUMBER_STYLE_OPTIONS)
        idx = NUMBER_STYLE_OPTIONS.index(node.number_style) if node.number_style in NUMBER_STYLE_OPTIONS else 0
        self._style_combo.setCurrentIndex(idx)
        self._style_combo.currentIndexChanged.connect(self._on_style)
        src_lay.addWidget(self._style_combo)
        lay.addWidget(src_w)

    def _on_module(self, path: str) -> None:
        self._node.module = path
        self.changed.emit()

    def _on_label(self) -> None:
        self._node.label = self._label_edit.text().strip()
        self.changed.emit()

    def _on_style(self, idx: int) -> None:
        self._node.number_style = NUMBER_STYLE_OPTIONS[idx]
        self.changed.emit()

    def refresh(self, vault_dirs: list[str]) -> None:
        self._picker.setup(vault_dirs, self._node.module)


class _HeroBrandPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, node: _BlockNode, parent=None):
        super().__init__(parent)
        self._node = node
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(BodyLabel("品牌标题："))
        self._title_edit = LineEdit(self)
        self._title_edit.setPlaceholderText("品牌名称")
        self._title_edit.setText(node.title)
        self._title_edit.editingFinished.connect(self._on_title)
        lay.addWidget(self._title_edit, 1)

        lay.addWidget(BodyLabel("理由标签："))
        self._reason_edit = LineEdit(self)
        self._reason_edit.setText(node.reason_label)
        self._reason_edit.setMaximumWidth(140)
        self._reason_edit.editingFinished.connect(self._on_reason)
        lay.addWidget(self._reason_edit)

        lay.addWidget(BodyLabel("编号："))
        self._style_combo = ComboBox(self)
        self._style_combo.addItems(NUMBER_STYLE_OPTIONS)
        idx = NUMBER_STYLE_OPTIONS.index(node.number_style) if node.number_style in NUMBER_STYLE_OPTIONS else 0
        self._style_combo.setCurrentIndex(idx)
        self._style_combo.currentIndexChanged.connect(self._on_style)
        lay.addWidget(self._style_combo)

    def _on_title(self) -> None:
        self._node.title = self._title_edit.text().strip()
        self.changed.emit()

    def _on_reason(self) -> None:
        self._node.reason_label = self._reason_edit.text().strip()
        self.changed.emit()

    def _on_style(self, idx: int) -> None:
        self._node.number_style = NUMBER_STYLE_OPTIONS[idx]
        self.changed.emit()


class _CompetitorPoolPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, node: _BlockNode, vault_dirs: list[str], parent=None):
        super().__init__(parent)
        self._node = node
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        src_w = QWidget(self)
        src_lay = QHBoxLayout(src_w)
        src_lay.setContentsMargins(0, 0, 0, 0)
        src_lay.setSpacing(6)
        src_lay.addWidget(BodyLabel("目录："))
        self._picker = CascadePickerButton(src_w)
        self._picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._picker.setup(vault_dirs, node.module)
        self._picker.path_selected.connect(self._on_module)
        src_lay.addWidget(self._picker, 2)
        src_lay.addWidget(BodyLabel("理由标签："))
        self._reason_edit = LineEdit(src_w)
        self._reason_edit.setText(node.reason_label)
        self._reason_edit.setMaximumWidth(140)
        self._reason_edit.editingFinished.connect(self._on_reason)
        src_lay.addWidget(self._reason_edit)
        src_lay.addStretch(1)
        lay.addWidget(src_w)

    def _on_module(self, path: str) -> None:
        self._node.module = path
        self.changed.emit()

    def _on_reason(self) -> None:
        self._node.reason_label = self._reason_edit.text().strip()
        self.changed.emit()

    def refresh(self, vault_dirs: list[str]) -> None:
        self._picker.setup(vault_dirs, self._node.module)


class _LiteralPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, node: _BlockNode, parent=None):
        super().__init__(parent)
        self._node = node
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._text_edit = TextEdit(self)
        self._text_edit.setPlaceholderText("输入固定文本内容…")
        self._text_edit.setPlainText(node.literal_text)
        self._text_edit.setMinimumHeight(60)
        self._text_edit.setMaximumHeight(120)
        self._text_edit.textChanged.connect(self._on_text)
        lay.addWidget(self._text_edit)

    def _on_text(self) -> None:
        self._node.literal_text = self._text_edit.toPlainText()
        self.changed.emit()


# ── Block row widget ──────────────────────────────────────────────────────────

class _BlockRow(CardWidget):
    """One visual row with kind selector + stacked per-kind field page."""

    expand_toggled = pyqtSignal()
    move_up        = pyqtSignal()
    move_down      = pyqtSignal()
    delete_req     = pyqtSignal()
    data_changed   = pyqtSignal()
    gear_requested      = pyqtSignal()
    add_child_requested = pyqtSignal()

    _INDENT_PX = 28

    def __init__(
        self,
        node: _BlockNode,
        position: str,
        level: int,
        vault_dirs: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self._node = node
        self._vault_dirs = vault_dirs

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16 + level * self._INDENT_PX, 8, 12, 8)
        outer.setSpacing(6)

        # ── Position label ────────────────────────────────────────────────
        pos_lbl = SubtitleLabel(position)
        pos_lbl.setFixedWidth(max(32, 14 * len(position)))
        pos_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(pos_lbl)

        # ── Expand chevron (paragraph only) ──────────────────────────────
        self._expand_btn = TransparentToolButton(FluentIcon.CHEVRON_RIGHT, self)
        self._expand_btn.setFixedSize(26, 26)
        self._expand_btn.clicked.connect(self.expand_toggled)
        self._expand_btn.setVisible(node.kind == "paragraph")
        outer.addWidget(self._expand_btn)

        # ── Kind selector ─────────────────────────────────────────────────
        self._kind_combo = ComboBox(self)
        for k in BLOCK_KINDS:
            self._kind_combo.addItem(BLOCK_KIND_LABELS[k])
        curr_idx = BLOCK_KINDS.index(node.kind) if node.kind in BLOCK_KINDS else 0
        self._kind_combo.setCurrentIndex(curr_idx)
        self._kind_combo.setMaximumWidth(110)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        outer.addWidget(self._kind_combo)

        # ── Stacked per-kind pages ────────────────────────────────────────
        self._stack = QStackedWidget(self)

        self._para_page = _ParagraphPage(node, vault_dirs, self._stack)
        self._para_page.changed.connect(self.data_changed)
        self._stack.addWidget(self._para_page)  # index 0 = paragraph

        self._heading_page = _HeadingPage(node, self._stack)
        self._heading_page.changed.connect(self.data_changed)
        self._stack.addWidget(self._heading_page)  # index 1 = heading

        self._numlist_page = _NumberedListPage(node, vault_dirs, self._stack)
        self._numlist_page.changed.connect(self.data_changed)
        self._stack.addWidget(self._numlist_page)  # index 2 = numbered_list

        self._hero_page = _HeroBrandPage(node, self._stack)
        self._hero_page.changed.connect(self.data_changed)
        self._stack.addWidget(self._hero_page)  # index 3 = hero_brand

        self._comp_page = _CompetitorPoolPage(node, vault_dirs, self._stack)
        self._comp_page.changed.connect(self.data_changed)
        self._stack.addWidget(self._comp_page)  # index 4 = competitor_pool

        self._literal_page = _LiteralPage(node, self._stack)
        self._literal_page.changed.connect(self.data_changed)
        self._stack.addWidget(self._literal_page)  # index 5 = literal

        self._stack.setCurrentIndex(curr_idx)
        outer.addWidget(self._stack, 1)

        # ── Action buttons ────────────────────────────────────────────────
        self._gear_btn = TransparentToolButton(FluentIcon.SETTING, self)
        self._gear_btn.setFixedSize(28, 28)
        self._gear_btn.setToolTip("高级配置（筛选 / 采样 / 依赖）")
        self._gear_btn.clicked.connect(lambda: self.gear_requested.emit())
        self._gear_btn.setVisible(node.kind in {"paragraph", "numbered_list", "competitor_pool"})
        outer.addWidget(self._gear_btn)

        self._add_child_btn = TransparentToolButton(FluentIcon.ADD, self)
        self._add_child_btn.setFixedSize(28, 28)
        self._add_child_btn.setToolTip("添加子段落")
        self._add_child_btn.clicked.connect(lambda: self.add_child_requested.emit())
        self._add_child_btn.setVisible(node.kind == "paragraph")
        outer.addWidget(self._add_child_btn)

        for icon, sig in [
            (FluentIcon.DOWN,   self.move_down),
            (FluentIcon.UP,     self.move_up),
            (FluentIcon.DELETE, self.delete_req),
        ]:
            btn = TransparentToolButton(icon, self)
            btn.setFixedSize(28, 28)
            btn.clicked.connect(sig)
            outer.addWidget(btn)

        self._update_expand_icon()

    def _on_kind_changed(self, idx: int) -> None:
        new_kind = BLOCK_KINDS[idx]
        self._node.kind = new_kind
        self._stack.setCurrentIndex(idx)
        is_para = new_kind == "paragraph"
        is_gearable = new_kind in {"paragraph", "numbered_list", "competitor_pool"}
        self._expand_btn.setVisible(is_para)
        self._gear_btn.setVisible(is_gearable)
        self._add_child_btn.setVisible(is_para)
        self._update_expand_icon()
        self.data_changed.emit()

    def _update_expand_icon(self) -> None:
        if self._node.kind != "paragraph":
            self._expand_btn.setVisible(False)
            return
        has_children = bool(self._node.children)
        self._expand_btn.setVisible(has_children)
        if has_children and self._node.expanded:
            self._expand_btn.setIcon(FluentIcon.CHEVRON_DOWN_MED)
        else:
            self._expand_btn.setIcon(FluentIcon.CHEVRON_RIGHT)

    def refresh_icon(self) -> None:
        self._update_expand_icon()

    def refresh_vault(self, vault_dirs: list[str]) -> None:
        self._vault_dirs = vault_dirs
        self._para_page.refresh(vault_dirs)
        self._numlist_page.refresh(vault_dirs)
        self._comp_page.refresh(vault_dirs)


# ── Main tree widget ──────────────────────────────────────────────────────────

class SlotTreeWidget(QWidget):
    """Hierarchical block list supporting all 6 block kinds.

    Public API:
        load_blocks(blocks)          — populate from list[Block]
        get_blocks() -> list[Block]  — return validated pydantic Block objects
        set_vault_root(p)            — update vault path
        add_root_block(kind)         — append new empty top-level block

    Backward-compat aliases (deprecated):
        load_slots(slots)   → load_blocks(blocks)
        get_slots()         → get_blocks()
        add_root_slot()     → add_root_block()

    Signal:
        slots_changed       — emitted on any structural or data change
    """

    slots_changed = pyqtSignal()

    def __init__(self, vault_root: Path | None = None, parent=None):
        super().__init__(parent)
        self._vault_root: Path | None = vault_root
        self._vault_dirs: list[str] = _scan_vault_dirs(vault_root) if vault_root else []
        self._roots: list[_BlockNode] = []

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

    def load_blocks(self, blocks: list[Block]) -> None:
        """Rebuild the tree from a list of Block objects."""
        self._roots = [_BlockNode.from_block(b) for b in blocks]
        self._rebuild()

    def get_blocks(self) -> list[Block]:
        """Return a list of validated pydantic Block objects."""
        out: list[Block] = []
        for i, n in enumerate(self._roots):
            bid = f"block_{i + 1}"
            out.append(n.to_block(bid))
        return out

    def add_root_block(self, kind: str = "paragraph") -> None:
        node = _BlockNode(kind=kind)
        self._roots.append(node)
        self._rebuild()
        self.slots_changed.emit()

    def _all_rows_for_test(self) -> list["_BlockRow"]:
        """Test helper: flat list of every visible ``_BlockRow``."""
        rows: list[_BlockRow] = []
        for i in range(self._lo.count()):
            item = self._lo.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, _BlockRow):
                rows.append(w)
        return rows

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

    # ── Backward-compat aliases ───────────────────────────────────────────────

    def load_slots(self, slots) -> None:  # type: ignore[override]
        """Deprecated: use load_blocks()."""
        # slots could be old Slot objects or new Block objects
        # Try new block API first
        try:
            from csm_core.template.schema import Block as _Block
            self.load_blocks(slots)
        except Exception:
            pass

    def get_slots(self):
        """Deprecated: use get_blocks()."""
        return self.get_blocks()

    def add_root_slot(self) -> None:
        """Deprecated: use add_root_block()."""
        self.add_root_block()

    # ── Internal rebuild ──────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        while self._lo.count() > 1:
            item = self._lo.takeAt(0)
            if (w := item.widget()):
                w.setParent(None)
                w.deleteLater()
        self._render_nodes(self._roots, parent_pos="", level=0)

    def _render_nodes(
        self, nodes: list[_BlockNode], parent_pos: str, level: int
    ) -> None:
        for i, node in enumerate(nodes):
            pos = f"{parent_pos}-{i + 1}" if parent_pos else str(i + 1)
            row = _BlockRow(node, pos, level, self._vault_dirs, self._inner)

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
            row.gear_requested.connect(lambda _n=node: self._open_gear_dialog(_n))
            row.add_child_requested.connect(lambda _n=node: self._add_child(_n))

            self._lo.insertWidget(self._lo.count() - 1, row)

            # Recursively render children if expanded (paragraph only)
            if node.kind == "paragraph" and node.expanded and node.children:
                self._render_nodes(node.children, pos, level + 1)

    # ── Node operations ───────────────────────────────────────────────────────

    def _on_toggle(self, node: _BlockNode) -> None:
        node.expanded = not node.expanded
        self._rebuild()

    def _move_node(self, siblings: list[_BlockNode], idx: int, delta: int) -> None:
        tgt = idx + delta
        if 0 <= tgt < len(siblings):
            siblings[idx], siblings[tgt] = siblings[tgt], siblings[idx]
            self._rebuild()
            self.slots_changed.emit()

    def _delete_node(self, siblings: list[_BlockNode], idx: int) -> None:
        siblings.pop(idx)
        QTimer.singleShot(0, self._rebuild_and_emit)

    def _delete_by_ref(self, target: _BlockNode) -> None:
        def _remove(nodes: list[_BlockNode]) -> bool:
            for i, n in enumerate(nodes):
                if n is target:
                    nodes.pop(i)
                    return True
                if n.kind == "paragraph" and _remove(n.children):
                    return True
            return False
        _remove(self._roots)
        QTimer.singleShot(0, self._rebuild_and_emit)

    def _rebuild_and_emit(self) -> None:
        self._rebuild()
        self.slots_changed.emit()

    def _open_gear_dialog(self, node: "_BlockNode") -> None:
        from .block_advanced_dialog import BlockAdvancedDialog
        all_blocks = self._collect_all_blocks()
        dlg = BlockAdvancedDialog(
            node=node,
            all_blocks=all_blocks,
            vault_root=getattr(self, "_vault_root", None),
            parent=self,
        )
        if dlg.exec():
            self._rebuild()
            self.slots_changed.emit()

    def _add_child(self, parent: _BlockNode) -> None:
        """Add a child paragraph block to a paragraph parent."""
        base_label = parent.label or Path(parent.module).name or "段落"
        child_label = f"{base_label} - 变体{len(parent.children) + 1}"
        child = _BlockNode(
            kind="paragraph",
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
