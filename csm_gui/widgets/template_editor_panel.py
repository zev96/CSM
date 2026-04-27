"""Template editor — single-page layout matching prototype/template.jsx.

The previous design used a 3-tab Pivot (基础设置 / 模块 / JSON 预览). The
new design folds template metadata into a header bar (chip + title input
+ 预览 + 保存模板) with a subtitle line, then drops straight into the
block list (SlotTreeWidget). 产品 and 默认 Skill sit in a compact row
just below the header; the JSON preview is reachable via a small text
button at the bottom-right (validate replaces the dedicated tab).
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QSplitter,
)

try:
    from qfluentwidgets import CaptionLabel
except ImportError:  # pragma: no cover
    from qfluentwidgets import BodyLabel as CaptionLabel  # type: ignore[assignment]

from qfluentwidgets import (
    BodyLabel, LineEdit, ComboBox,
    PrimaryPushButton, PushButton, FluentIcon,
    InfoBar, InfoBarPosition, MessageBoxBase,
)

from csm_core.template.schema import Template
from csm_core.template.loader import load_template, save_template
from .block_list_widget import BlockListWidget
from .block_inspector import BlockInspector


# ── Design tokens ────────────────────────────────────────────────────────────
_INK   = "#1e1c19"
_INK_2 = "rgba(30,28,25,0.62)"
_INK_3 = "rgba(30,28,25,0.38)"
_INK_5 = "rgba(30,28,25,0.08)"
_ACCENT = "#2f6f5e"


class _JsonPreviewDialog(MessageBoxBase):
    """JSON 预览 + 校验 — used in place of the old JSON tab."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.widget.setMinimumSize(640, 520)
        from qfluentwidgets import SubtitleLabel, PlainTextEdit
        self.viewLayout.addWidget(SubtitleLabel("JSON 预览", self))
        self._edit = PlainTextEdit(self)
        self._edit.setReadOnly(True)
        self._edit.setPlainText(text)
        self.viewLayout.addWidget(self._edit, 1)
        self.yesButton.setText("关闭")
        self.cancelButton.hide()


class TemplateEditorPanel(QWidget):
    """Single-page template editor with header bar + block list body."""

    saved = pyqtSignal(Path)
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TemplateEditorPanel")
        self.setStyleSheet("#TemplateEditorPanel { background: transparent; }")

        self._current_path: Path | None = None
        self._template_id: str = ""
        self._dirty = False
        self._vault_root: Path | None = None
        self._skill_dir: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header card (chip + title + actions) ──────────────────────────
        header_card = QFrame(self)
        header_card.setObjectName("TplHeaderCard")
        header_card.setStyleSheet(
            f"#TplHeaderCard {{ background: #ffffff; border: 1px solid {_INK_5};"
            f" border-radius: 12px; }}"
        )
        h_lay = QVBoxLayout(header_card)
        h_lay.setContentsMargins(20, 14, 20, 14)
        h_lay.setSpacing(6)

        title_row = QHBoxLayout(); title_row.setSpacing(10)
        chip = QLabel("模板", header_card)
        chip.setStyleSheet(
            f"padding: 2px 10px; border-radius: 999px;"
            f"border: 1px solid rgba(30,28,25,0.18); background: transparent;"
            f"font-size: 11.5px; color: {_INK_2};")
        chip.setFixedHeight(22)
        title_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)

        self.name_input = LineEdit(header_card)
        self.name_input.setPlaceholderText("模板名称")
        self.name_input.setStyleSheet(
            "LineEdit { font-size: 18px; font-weight: 600; border: none;"
            " background: transparent; padding: 4px 6px; }"
            "LineEdit:hover { background: rgba(30,28,25,0.04); border-radius: 6px; }"
            "LineEdit:focus { background: rgba(30,28,25,0.04); border-radius: 6px; }"
        )
        self.name_input.setMinimumHeight(34)
        self.name_input.textChanged.connect(self._mark_dirty)
        title_row.addWidget(self.name_input, 1)

        self.preview_btn = PushButton(FluentIcon.VIEW, "预览", header_card)
        self.preview_btn.clicked.connect(self._show_json_preview)
        title_row.addWidget(self.preview_btn)
        self.save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存模板", header_card)
        self.save_btn.clicked.connect(self._save)
        title_row.addWidget(self.save_btn)
        h_lay.addLayout(title_row)

        # Subtitle row (dynamic count + meta)
        self._subtitle = QLabel("—", header_card)
        self._subtitle.setStyleSheet(
            f"color: {_INK_2}; font-size: 12.5px; background: transparent;"
            "padding-left: 2px;")
        h_lay.addWidget(self._subtitle)

        # 产品 + 默认 Skill compact row
        meta_row = QHBoxLayout(); meta_row.setSpacing(10); meta_row.setContentsMargins(0, 6, 0, 0)
        meta_row.addWidget(self._meta_label("产品"))
        self.product_input = LineEdit(header_card)
        self.product_input.setPlaceholderText("如：吸尘器")
        self.product_input.setMaximumWidth(220)
        self.product_input.textChanged.connect(self._mark_dirty)
        meta_row.addWidget(self.product_input)
        meta_row.addSpacing(12)
        meta_row.addWidget(self._meta_label("默认 Skill"))
        self.default_skill_combo = ComboBox(header_card)
        self.default_skill_combo.addItem("（无）")
        self.default_skill_combo.setMinimumWidth(180)
        self.default_skill_combo.currentIndexChanged.connect(self._mark_dirty)
        meta_row.addWidget(self.default_skill_combo)
        meta_row.addStretch(1)
        self.dirty_label = CaptionLabel("● 有未保存的更改", header_card)
        self.dirty_label.setStyleSheet(f"color: {_ACCENT}; font-size: 11.5px;")
        self.dirty_label.setVisible(False)
        meta_row.addWidget(self.dirty_label)
        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "返回模板库", header_card)
        self.back_btn.clicked.connect(self.back_requested.emit)
        meta_row.addWidget(self.back_btn)
        h_lay.addLayout(meta_row)

        page_wrap = QVBoxLayout()
        page_wrap.setContentsMargins(0, 0, 0, 12)
        page_wrap.addWidget(header_card)
        root.addLayout(page_wrap)

        # ── Body: split (left list + right inspector) ─────────────────────
        body = QSplitter(Qt.Orientation.Horizontal, self)
        body.setChildrenCollapsible(False)
        body.setStyleSheet("QSplitter::handle { background: transparent; width: 24px; }")
        body.setHandleWidth(24)

        # Left card
        left_card = QFrame(body)
        left_card.setObjectName("TplBodyCard")
        left_card.setStyleSheet(
            f"#TplBodyCard {{ background: transparent; border: none; }}"
        )
        left_lay = QVBoxLayout(left_card)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)

        self.block_list = BlockListWidget(parent=left_card)
        self.block_list.blocks_changed.connect(self._on_blocks_changed)
        self.block_list.block_selected.connect(self._on_block_selected)
        left_lay.addWidget(self.block_list, 1)

        # No FluentIcon — qfluentwidgets PushButton overlaps the icon with
        # centered text under custom QSS, so the "+" lives in the label.
        add_btn = PushButton("＋  添加新区块", left_card)
        add_btn.setFixedHeight(40)
        add_btn.setStyleSheet(
            f"PushButton {{ border: 1.5px dashed rgba(30,28,25,0.18);"
            f" background: transparent; color: {_INK_2}; border-radius: 10px;"
            f" padding: 4px 14px; font-size: 13px; }}"
            f"PushButton:hover {{ border-color: {_ACCENT}; color: {_ACCENT};"
            f" background: #ecf2ee; }}"
        )
        add_btn.clicked.connect(self._on_add_slot)
        self._add_btn = add_btn
        left_lay.addWidget(add_btn)
        body.addWidget(left_card)

        # Right inspector
        self.inspector = BlockInspector(body)
        self.inspector.set_all_blocks_provider(self._all_blocks_for_inspector)
        self.inspector.node_changed.connect(self._on_inspector_changed)
        self.inspector.delete_requested.connect(self._on_delete_requested)
        body.addWidget(self.inspector)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        body.setSizes([620, 360])
        root.addWidget(body, 1)

        # Ctrl+S shortcut
        sc = QShortcut(QKeySequence("Ctrl+S"), self)
        sc.activated.connect(self._save)

        self._set_enabled(False)

    # ── Helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _meta_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_INK_3}; font-size: 12px; background: transparent;")
        return lbl

    # ── Public API ───────────────────────────────────────────────────────
    def load_template(self, path: Path) -> None:
        try:
            tpl = load_template(path)
        except Exception as exc:
            InfoBar.error(
                "加载失败", str(exc).splitlines()[0],
                parent=self.window(), position=InfoBarPosition.TOP,
            )
            return

        self._current_path = path
        self._template_id = tpl.id

        for w, val in (
            (self.name_input, tpl.name),
            (self.product_input, tpl.product),
        ):
            w.blockSignals(True)
            try:
                w.setText(val)
            finally:
                w.blockSignals(False)

        self.default_skill_combo.blockSignals(True)
        try:
            target = tpl.default_skill_id or ""
            idx = 0
            for i in range(self.default_skill_combo.count()):
                if self.default_skill_combo.itemText(i) == target:
                    idx = i
                    break
            self.default_skill_combo.setCurrentIndex(idx)
        finally:
            self.default_skill_combo.blockSignals(False)

        self.block_list.load_blocks(tpl.blocks)

        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(True)
        self._refresh_subtitle()

    def is_dirty(self) -> bool:
        return self._dirty

    def save(self) -> bool:
        return self._save()

    def clear(self) -> None:
        self._current_path = None
        self._template_id = ""
        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(False)

    def set_vault_root(self, path: Path | None) -> None:
        self._vault_root = path
        self.block_list.set_vault_root(path)
        self.inspector.set_vault(path, self.block_list.vault_dirs())

    def set_skill_dir(self, skill_dir: Path | None) -> None:
        self._skill_dir = Path(skill_dir) if skill_dir else None
        previous = self.default_skill_combo.currentText()
        self.default_skill_combo.blockSignals(True)
        try:
            self.default_skill_combo.clear()
            self.default_skill_combo.addItem("（无）")
            if self._skill_dir and self._skill_dir.is_dir():
                for p in sorted(self._skill_dir.glob("*.md")):
                    self.default_skill_combo.addItem(p.stem)
            if previous and previous != "（无）":
                restored = self.default_skill_combo.findText(previous)
                if restored >= 0:
                    self.default_skill_combo.setCurrentIndex(restored)
        finally:
            self.default_skill_combo.blockSignals(False)

    # ── Private ──────────────────────────────────────────────────────────
    def _set_enabled(self, enabled: bool) -> None:
        self.save_btn.setEnabled(enabled)
        self.preview_btn.setEnabled(enabled)
        self.name_input.setEnabled(enabled)
        self.product_input.setEnabled(enabled)
        self.default_skill_combo.setEnabled(enabled)

    def _mark_dirty(self, *_) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirty_label.setVisible(True)
        self._refresh_subtitle()

    def _refresh_subtitle(self) -> None:
        if self._current_path is None:
            self._subtitle.setText("—")
            return
        try:
            n = len(self.block_list.get_blocks())
        except Exception:
            n = 0
        skill = self.default_skill_combo.currentText() or "—"
        self._subtitle.setText(
            f"按顺序搭建文章骨架 · 每块绑定 Skill 和素材 · {n} 块结构 · 默认 Skill：{skill}"
        )

    def _on_blocks_changed(self) -> None:
        self._mark_dirty()
        self._refresh_subtitle()

    def _on_block_selected(self, idx: int) -> None:
        node = self.block_list.current_node()
        self.inspector.set_node(idx, self.block_list.total(), node)

    def _on_inspector_changed(self) -> None:
        self.block_list.refresh_current_row()
        self._mark_dirty()
        self._refresh_subtitle()

    def _all_blocks_for_inspector(self):
        roots = [self.block_list._roots[i] for i in range(self.block_list.total())]
        return [(f"block_{i + 1}", n.label or n.text or f"block_{i + 1}", n)
                for i, n in enumerate(roots)]

    def _on_delete_requested(self) -> None:
        idx = self.block_list.selected_index()
        if idx < 0:
            return
        self.block_list._delete(idx)

    def _build_template_dict(self) -> dict:
        # Inline advanced sections defer writing until we ask.
        self.inspector.commit_advanced()
        blocks = self.block_list.get_blocks()
        skill_text = self.default_skill_combo.currentText()
        default_skill_id = None if skill_text == "（无）" else skill_text
        return {
            "id": self._template_id,
            "name": self.name_input.text().strip(),
            "product": self.product_input.text().strip(),
            "default_skill_id": default_skill_id,
            "blocks": [b.model_dump() for b in blocks],
        }

    def _show_json_preview(self) -> None:
        if self._current_path is None:
            return
        try:
            d = self._build_template_dict()
            text = json.dumps(d, ensure_ascii=False, indent=2)
        except Exception as exc:
            text = f"// 当前状态序列化失败: {exc}"
        dlg = _JsonPreviewDialog(text, self.window())
        dlg.exec()

    def _save(self) -> bool:
        if self._current_path is None:
            return False
        try:
            d = self._build_template_dict()
            tpl = Template.model_validate(d)
        except Exception as exc:
            first = str(exc).splitlines()[0]
            InfoBar.error(
                "保存失败：校验未通过", first,
                parent=self.window(), position=InfoBarPosition.TOP, duration=-1,
            )
            return False
        try:
            save_template(tpl, self._current_path)
        except Exception as exc:
            InfoBar.error(
                "保存失败：写文件错误", str(exc).splitlines()[0],
                parent=self.window(), position=InfoBarPosition.TOP, duration=-1,
            )
            return False
        self._dirty = False
        self.dirty_label.setVisible(False)
        InfoBar.success(
            "模板已保存", str(self._current_path.name),
            parent=self.window(), position=InfoBarPosition.TOP, duration=3000,
        )
        self.saved.emit(self._current_path)
        return True

    def _on_add_slot(self) -> None:
        from qfluentwidgets import RoundMenu, Action
        from .slot_tree_widget import BLOCK_KINDS, BLOCK_KIND_LABELS
        menu = RoundMenu(parent=self._add_btn)
        for k in BLOCK_KINDS:
            act = Action(BLOCK_KIND_LABELS.get(k, k), self._add_btn)
            act.triggered.connect(lambda _=False, _k=k: self.block_list.add_root_block(_k))
            menu.addAction(act)
        menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().topLeft()))
