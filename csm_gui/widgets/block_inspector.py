"""Right-side per-block inspector for the template editor.

Mirrors ``cms/project/prototype/template.jsx`` inspector card:
区块 X / N · name · 区块名 · 目录 · kind-specific fields · (inline) 高级设置
· 删除。Mutates the bound ``_BlockNode`` in place; emits ``node_changed``
when edits land so the editor can mark dirty + repaint the list row.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QSizePolicy,
    QAbstractSpinBox, QAbstractButton,
)
from qfluentwidgets import (
    LineEdit, PlainTextEdit, ComboBox, PushButton,
    FluentIcon, StrongBodyLabel,
)

from .slot_tree_widget import _BlockNode
from .cascade_picker import CascadePickerButton


_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT = "#2f6f5e"
_DANGER = "#c25c4d"


_KIND_LABELS = {
    "paragraph":      "段落",
    "heading":        "标题",
    "numbered_list":  "编号列表",
    "hero_brand":     "主推",
    "competitor_pool":"对比池",
    "literal":        "文本",
}

_NUMBER_STYLES = ["1.", "1）", "①", "一、", "(1)"]


def _field_label(text: str, parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    lbl.setStyleSheet(
        f"color: {_INK_2}; font-size: 12px; background: transparent;"
        "margin-bottom: 2px;")
    return lbl


def _section_divider(parent=None) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(
        f"color: {_INK_5}; background-color: {_INK_5}; border: none; max-height: 1px;")
    line.setFixedHeight(1)
    return line


class BlockInspector(QWidget):
    """Per-block inspector card. Bind via ``set_node(idx, total, node)``."""

    node_changed     = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BlockInspector")
        # Required so QSS background+border actually paints on a bare QWidget.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#BlockInspector {{ background: #ffffff;"
            f" border: 1px solid {_INK_5}; border-radius: 12px; }}"
        )
        self.setMinimumWidth(300)

        self._node: Optional[_BlockNode] = None
        self._vault_root: Path | None = None
        self._vault_dirs: list[str] = []
        self._all_blocks_provider = lambda: []  # set by editor
        self._suspend_signals = False
        # Inline advanced sections, rebuilt per selection.
        self._filter_section = None
        self._sample_section = None
        self._depends_section = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        self._root_lay = root

        # Eyebrow
        self._eyebrow = QLabel("—", self)
        self._eyebrow.setStyleSheet(
            f"color: {_INK_3}; font-size: 11.5px; letter-spacing: 0.6px;"
            "background: transparent;")
        root.addWidget(self._eyebrow)

        # Big title
        self._title = QLabel("未选择区块", self)
        self._title.setStyleSheet(
            f"color: {_INK}; font-size: 18px; font-weight: 600;"
            "letter-spacing: -0.2px; background: transparent;")
        self._title.setWordWrap(True)
        root.addWidget(self._title)

        # ── Field: 区块名 ────────────────────────────────────────────────
        self._lbl_name = _field_label("区块名", self)
        self._name_input = LineEdit(self)
        self._name_input.textChanged.connect(self._on_name_changed)
        root.addWidget(self._lbl_name)
        root.addWidget(self._name_input)

        # ── Field: 目录 (paragraph / numbered_list / competitor_pool) ────
        self._lbl_module = _field_label("目录", self)
        self._module_picker = CascadePickerButton(self)
        self._module_picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._module_picker.path_selected.connect(self._on_module_changed)
        root.addWidget(self._lbl_module)
        root.addWidget(self._module_picker)

        # ── Field: 序号 (heading) ────────────────────────────────────────
        self._lbl_index = _field_label("序号", self)
        self._index_input = LineEdit(self)
        self._index_input.setPlaceholderText("如：一")
        self._index_input.setMaximumWidth(120)
        self._index_input.textChanged.connect(self._on_index_changed)
        root.addWidget(self._lbl_index)
        root.addWidget(self._index_input)

        # ── Field: 编号样式 (numbered_list / hero_brand) ────────────────
        self._lbl_style = _field_label("编号样式", self)
        self._style_combo = ComboBox(self)
        for s in _NUMBER_STYLES:
            self._style_combo.addItem(s)
        self._style_combo.setMaximumWidth(140)
        self._style_combo.currentTextChanged.connect(self._on_style_changed)
        root.addWidget(self._lbl_style)
        root.addWidget(self._style_combo)

        # ── Field: 推荐理由 label (hero_brand / competitor_pool) ────────
        self._lbl_reason = _field_label("推荐理由前缀", self)
        self._reason_input = LineEdit(self)
        self._reason_input.setPlaceholderText("如：推荐理由：")
        self._reason_input.textChanged.connect(self._on_reason_changed)
        root.addWidget(self._lbl_reason)
        root.addWidget(self._reason_input)

        # ── Field: 文本 (heading text / literal text) ────────────────────
        self._lbl_text = _field_label("文本", self)
        self._text_input = PlainTextEdit(self)
        self._text_input.setPlaceholderText("…")
        self._text_input.setMaximumHeight(110)
        self._text_input.textChanged.connect(self._on_text_changed)
        root.addWidget(self._lbl_text)
        root.addWidget(self._text_input)

        # ── Inline advanced container (筛选 / 取值 / 链接) ────────────────
        self._adv_divider = _section_divider(self)
        root.addWidget(self._adv_divider)
        self._adv_container = QWidget(self)
        self._adv_container.setStyleSheet("background: transparent;")
        self._adv_lay = QVBoxLayout(self._adv_container)
        self._adv_lay.setContentsMargins(0, 0, 0, 0)
        self._adv_lay.setSpacing(8)
        root.addWidget(self._adv_container)

        # ── Divider + delete ──────────────────────────────────────────────
        self._del_divider = _section_divider(self)
        root.addWidget(self._del_divider)
        # Plain text — qfluentwidgets icon+text overlaps under custom QSS.
        self._delete_btn = PushButton("删除此区块", self)
        self._delete_btn.setFixedHeight(34)
        self._delete_btn.setStyleSheet(
            "PushButton { color: " + _DANGER + ";"
            " border: 1px solid rgba(194,92,77,0.32); background: transparent;"
            " border-radius: 8px; padding: 4px 14px; font-size: 13px; }"
            "PushButton:hover { background: rgba(194,92,77,0.08);"
            " border-color: " + _DANGER + "; }"
        )
        self._delete_btn.clicked.connect(self.delete_requested.emit)
        root.addWidget(self._delete_btn)

        root.addStretch(1)

        self.set_node(-1, 0, None)

    # ── Public API ───────────────────────────────────────────────────────
    def set_vault(self, vault_root: Path | None, vault_dirs: list[str]) -> None:
        self._vault_root = vault_root
        self._vault_dirs = list(vault_dirs)
        if self._node is not None and hasattr(self._node, "module"):
            self._module_picker.setup(self._vault_dirs, self._node.module or "")

    def set_all_blocks_provider(self, fn) -> None:
        """Editor passes a callable returning ``[(bid, label, node), ...]``."""
        self._all_blocks_provider = fn

    def commit_advanced(self) -> None:
        """Flush inline advanced sections into the bound node."""
        for sec in (self._filter_section, self._sample_section, self._depends_section):
            if sec is not None:
                try:
                    sec.save_to_node()
                except Exception:
                    pass

    def set_node(self, idx: int, total: int, node: Optional[_BlockNode]) -> None:
        # Flush any pending advanced edits from the previous selection.
        self.commit_advanced()
        self._node = node
        self._suspend_signals = True
        try:
            if node is None:
                self._eyebrow.setText("—")
                self._title.setText("未选择区块")
                self._set_all_visible(False)
                self._clear_advanced()
                self._adv_divider.setVisible(False)
                self._del_divider.setVisible(False)
                self._delete_btn.setVisible(False)
                return

            self._eyebrow.setText(
                f"区块 {idx + 1} / {total} · {_KIND_LABELS.get(node.kind, node.kind)}"
            )
            self._title.setText(self._friendly_title(node))

            self._set_all_visible(False)

            kind = node.kind
            self._show_name_field(kind)
            self._show_module_field(kind)
            self._show_kind_specific_fields(kind)
            self._rebuild_advanced(kind)

            self._del_divider.setVisible(True)
            self._delete_btn.setVisible(True)
        finally:
            self._suspend_signals = False

    # ── Field visibility helpers ─────────────────────────────────────────
    def _set_all_visible(self, vis: bool) -> None:
        for w in (
            self._lbl_name, self._name_input,
            self._lbl_module, self._module_picker,
            self._lbl_index, self._index_input,
            self._lbl_style, self._style_combo,
            self._lbl_reason, self._reason_input,
            self._lbl_text, self._text_input,
            self._delete_btn,
        ):
            w.setVisible(vis)

    def _show_name_field(self, kind: str) -> None:
        n = self._node
        if kind in {"paragraph", "numbered_list"}:
            self._name_input.blockSignals(True)
            self._name_input.setText(n.label or "")
            self._name_input.blockSignals(False)
            self._lbl_name.setVisible(True); self._name_input.setVisible(True)
        elif kind == "hero_brand":
            self._lbl_name.setText("标题")
            self._name_input.blockSignals(True)
            self._name_input.setText(n.title or "")
            self._name_input.blockSignals(False)
            self._lbl_name.setVisible(True); self._name_input.setVisible(True)
            return
        else:
            self._lbl_name.setVisible(False); self._name_input.setVisible(False)
        if kind != "hero_brand":
            self._lbl_name.setText("区块名")

    def _show_module_field(self, kind: str) -> None:
        if kind in {"paragraph", "numbered_list", "competitor_pool"}:
            self._module_picker.setup(self._vault_dirs, self._node.module or "")
            self._lbl_module.setVisible(True); self._module_picker.setVisible(True)

    def _show_kind_specific_fields(self, kind: str) -> None:
        n = self._node
        if kind == "heading":
            self._index_input.blockSignals(True)
            self._index_input.setText(n.index or "")
            self._index_input.blockSignals(False)
            self._lbl_index.setVisible(True); self._index_input.setVisible(True)
            self._lbl_text.setText("标题文本")
            self._text_input.blockSignals(True)
            self._text_input.setPlainText(n.text or "")
            self._text_input.blockSignals(False)
            self._text_input.setMaximumHeight(60)
            self._lbl_text.setVisible(True); self._text_input.setVisible(True)
        elif kind == "literal":
            self._lbl_text.setText("固定文本")
            self._text_input.blockSignals(True)
            self._text_input.setPlainText(n.literal_text or "")
            self._text_input.blockSignals(False)
            self._text_input.setMaximumHeight(160)
            self._lbl_text.setVisible(True); self._text_input.setVisible(True)
        elif kind == "numbered_list":
            self._style_combo.blockSignals(True)
            i = self._style_combo.findText(n.number_style)
            self._style_combo.setCurrentIndex(i if i >= 0 else 0)
            self._style_combo.blockSignals(False)
            self._lbl_style.setVisible(True); self._style_combo.setVisible(True)
        elif kind == "hero_brand":
            self._style_combo.blockSignals(True)
            i = self._style_combo.findText(n.number_style)
            self._style_combo.setCurrentIndex(i if i >= 0 else 0)
            self._style_combo.blockSignals(False)
            self._lbl_style.setVisible(True); self._style_combo.setVisible(True)
            self._reason_input.blockSignals(True)
            self._reason_input.setText(n.reason_label or "")
            self._reason_input.blockSignals(False)
            self._lbl_reason.setVisible(True); self._reason_input.setVisible(True)
        elif kind == "competitor_pool":
            self._reason_input.blockSignals(True)
            self._reason_input.setText(n.reason_label or "")
            self._reason_input.blockSignals(False)
            self._lbl_reason.setVisible(True); self._reason_input.setVisible(True)

    # ── Inline advanced section ──────────────────────────────────────────
    def _clear_advanced(self) -> None:
        while self._adv_lay.count():
            it = self._adv_lay.takeAt(0)
            if (w := it.widget()):
                w.setParent(None)
                w.deleteLater()
        self._filter_section = None
        self._sample_section = None
        self._depends_section = None

    def _rebuild_advanced(self, kind: str) -> None:
        self._clear_advanced()
        has_adv = kind in {"paragraph", "numbered_list", "competitor_pool"}
        self._adv_divider.setVisible(has_adv)
        self._adv_container.setVisible(has_adv)
        if not has_adv:
            return

        from .block_advanced_dialog import (
            _FilterSection, _SampleSection, _DependsSection,
        )
        from .slot_tree_widget import _scan_frontmatter

        # Section heading
        title_map = {
            "paragraph": "段落高级设置",
            "numbered_list": "列表高级设置",
            "competitor_pool": "对比池高级设置",
        }
        head = StrongBodyLabel(title_map.get(kind, "高级设置"), self._adv_container)
        head.setStyleSheet(f"color: {_INK}; background: transparent;")
        self._adv_lay.addWidget(head)

        node = self._node
        fm_candidates: dict[str, list[str]] = {}
        if self._vault_root is not None and getattr(node, "module", ""):
            try:
                mod_dir = Path(self._vault_root) / node.module
                if mod_dir.exists():
                    fm_candidates = _scan_frontmatter(mod_dir)
            except Exception:
                fm_candidates = {}

        self._adv_lay.addWidget(_field_label("筛选", self._adv_container))
        self._filter_section = _FilterSection(node, fm_candidates, parent=self._adv_container)
        self._adv_lay.addWidget(self._filter_section)

        self._adv_lay.addWidget(_field_label("取值", self._adv_container))
        self._sample_section = _SampleSection(node, parent=self._adv_container)
        self._sample_section.set_paragraph_only_fields_visible(kind == "paragraph")
        self._adv_lay.addWidget(self._sample_section)

        if kind == "paragraph":
            self._adv_lay.addWidget(_field_label("链接", self._adv_container))
            all_blocks = list(self._all_blocks_provider() or [])
            self._depends_section = _DependsSection(
                node, all_blocks, parent_widget=self._adv_container)
            self._adv_lay.addWidget(self._depends_section)

        # Wire change-detection on common widget signals so the editor can
        # mark dirty when any inline-advanced field is touched.
        for sec in (self._filter_section, self._sample_section, self._depends_section):
            if sec is not None:
                self._install_dirty_listeners(sec)

    def _install_dirty_listeners(self, root_widget: QWidget) -> None:
        for w in root_widget.findChildren(QWidget):
            if isinstance(w, LineEdit):
                w.textChanged.connect(self._on_advanced_edited)
            elif isinstance(w, ComboBox):
                w.currentTextChanged.connect(self._on_advanced_edited)
            elif isinstance(w, QAbstractSpinBox):
                # SpinBox emits valueChanged via QSpinBox base
                if hasattr(w, "valueChanged"):
                    try:
                        w.valueChanged.connect(self._on_advanced_edited)
                    except Exception:
                        pass
            elif isinstance(w, QAbstractButton) and w.isCheckable():
                w.toggled.connect(self._on_advanced_edited)

    def _on_advanced_edited(self, *_) -> None:
        if self._suspend_signals:
            return
        self.node_changed.emit()

    @staticmethod
    def _friendly_title(node: _BlockNode) -> str:
        kind = node.kind
        if kind == "heading":
            return node.text or "（未填写）"
        if kind == "hero_brand":
            return node.title or "（未填写）"
        if kind == "literal":
            txt = (node.literal_text or "").splitlines()
            return txt[0][:32] if txt and txt[0] else "（空文本）"
        return node.label or _KIND_LABELS.get(kind, "区块")

    # ── Edit slots ───────────────────────────────────────────────────────
    def _on_name_changed(self, text: str) -> None:
        if self._suspend_signals or self._node is None:
            return
        kind = self._node.kind
        if kind in {"paragraph", "numbered_list"}:
            self._node.label = text.strip()
        elif kind == "hero_brand":
            self._node.title = text.strip()
        else:
            return
        self._title.setText(self._friendly_title(self._node))
        self.node_changed.emit()

    def _on_module_changed(self, path: str) -> None:
        if self._suspend_signals or self._node is None:
            return
        if not hasattr(self._node, "module"):
            return
        self._node.module = path
        if self._node.kind in {"paragraph", "numbered_list"} and not self._node.label:
            self._node.label = Path(path).name
            self._suspend_signals = True
            try:
                self._name_input.setText(self._node.label)
            finally:
                self._suspend_signals = False
            self._title.setText(self._friendly_title(self._node))
        # Flush pending filter rows, then rebuild so the new module's
        # frontmatter populates the key/value dropdowns.
        self.commit_advanced()
        self._suspend_signals = True
        try:
            self._rebuild_advanced(self._node.kind)
        finally:
            self._suspend_signals = False
        self.node_changed.emit()

    def _on_index_changed(self, text: str) -> None:
        if self._suspend_signals or self._node is None:
            return
        self._node.index = text.strip()
        self.node_changed.emit()

    def _on_style_changed(self, text: str) -> None:
        if self._suspend_signals or self._node is None:
            return
        self._node.number_style = text
        self.node_changed.emit()

    def _on_reason_changed(self, text: str) -> None:
        if self._suspend_signals or self._node is None:
            return
        self._node.reason_label = text
        self.node_changed.emit()

    def _on_text_changed(self) -> None:
        if self._suspend_signals or self._node is None:
            return
        text = self._text_input.toPlainText()
        if self._node.kind == "heading":
            self._node.text = text.strip()
        elif self._node.kind == "literal":
            self._node.literal_text = text
        else:
            return
        self._title.setText(self._friendly_title(self._node))
        self.node_changed.emit()
