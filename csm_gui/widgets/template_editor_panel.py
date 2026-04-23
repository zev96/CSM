"""Right-side template editor panel — three-tab Pivot for editing a template.

Tabs:
  1. 基础设置 — name / product / default skill
  2. Slots    — ordered list with edit/up/down/delete + add-slot button
  3. JSON预览 — read-only live JSON + validate button

Bottom bar (shared):
  dirty indicator  +  Save button  (Ctrl+S shortcut)

UI patterns follow the existing codebase:
  • ScrollArea skeleton  (setStyleSheet "transparent; border: none")
  • CardWidget  ContentsMargins(16,12,16,12)  spacing 6
  • StrongBodyLabel for card titles, BodyLabel for field labels
  • PrimaryPushButton(FluentIcon.X, text, parent) height 40
  • PushButton height 38, TransparentToolButton for icon-only buttons
  • Pivot + QStackedWidget (same pattern as home_page.py)
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
)

try:
    from qfluentwidgets import CaptionLabel
except ImportError:  # pragma: no cover
    from qfluentwidgets import BodyLabel as CaptionLabel  # type: ignore[assignment]

from qfluentwidgets import (
    StrongBodyLabel, BodyLabel,
    LineEdit, PlainTextEdit, ComboBox,
    PrimaryPushButton, PushButton, FluentIcon,
    ScrollArea, CardWidget, Pivot,
    InfoBar, InfoBarPosition, MessageBox,
)

from csm_core.template.schema import Template
from csm_core.template.loader import load_template, save_template
from .slot_tree_widget import SlotTreeWidget


# (old _SlotRow and _SlotsPage replaced by SlotTreeWidget from slot_tree_widget.py)


# ---------------------------------------------------------------------------
# Main editor panel
# ---------------------------------------------------------------------------

class TemplateEditorPanel(QWidget):
    """Right-side editor panel with Pivot tabs.

    Signals
    -------
    saved(Path):
        Emitted when the template is successfully saved to disk.
    """

    saved = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Path | None = None
        self._template_id: str = ""
        self._dirty = False
        self._vault_root: Path | None = None
        self._skill_dir: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Pivot tabs ────────────────────────────────────────────────────
        self.pivot = Pivot(self)
        self.stack = QStackedWidget(self)

        self.pivot.addItem(routeKey="info",  text="基础设置",
                           onClick=lambda: self.stack.setCurrentIndex(0))
        self.pivot.addItem(routeKey="slots", text="模块",
                           onClick=lambda: self.stack.setCurrentIndex(1))
        self.pivot.addItem(routeKey="json",  text="JSON 预览",
                           onClick=lambda: self.stack.setCurrentIndex(2))
        self.pivot.setCurrentItem("info")

        root.addWidget(self.pivot)
        root.addWidget(self.stack, 1)

        # ── Tab 1: 基本信息 ───────────────────────────────────────────────
        self.stack.addWidget(self._build_info_tab())

        # ── Tab 2: Slots ──────────────────────────────────────────────────
        self.stack.addWidget(self._build_slots_tab())

        # ── Tab 3: JSON 预览 ──────────────────────────────────────────────
        self.stack.addWidget(self._build_json_tab())

        # ── Bottom save bar ───────────────────────────────────────────────
        bar = QWidget(self)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(16, 8, 16, 8)
        self.dirty_label = BodyLabel("● 有未保存的更改", bar)
        self.dirty_label.setVisible(False)
        bar_lay.addWidget(self.dirty_label)
        bar_lay.addStretch(1)
        self.save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存", bar)
        self.save_btn.setFixedHeight(40)
        self.save_btn.clicked.connect(self._save)
        bar_lay.addWidget(self.save_btn)
        root.addWidget(bar)

        # Ctrl+S shortcut
        sc = QShortcut(QKeySequence("Ctrl+S"), self)
        sc.activated.connect(self._save)

        self._set_enabled(False)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_info_tab(self) -> QWidget:
        page = ScrollArea(self)
        page.setWidgetResizable(True)
        page.setStyleSheet(
            "QScrollArea, #scrollWidget {background: transparent; border: none;}"
        )
        inner = QWidget()
        inner.setObjectName("scrollWidget")
        page.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        basic_card = CardWidget(inner)
        basic_lay = QVBoxLayout(basic_card)
        basic_lay.setContentsMargins(16, 12, 16, 12)
        basic_lay.setSpacing(6)
        basic_lay.addWidget(StrongBodyLabel("基础设置"))

        basic_lay.addWidget(BodyLabel("名称"))
        self.name_input = LineEdit(basic_card)
        self.name_input.textChanged.connect(self._mark_dirty)
        basic_lay.addWidget(self.name_input)

        basic_lay.addWidget(BodyLabel("产品"))
        self.product_input = LineEdit(basic_card)
        self.product_input.textChanged.connect(self._mark_dirty)
        basic_lay.addWidget(self.product_input)

        basic_lay.addWidget(BodyLabel("默认 Skill"))
        self.default_skill_combo = ComboBox(basic_card)
        self.default_skill_combo.addItem("（无）")
        self.default_skill_combo.currentIndexChanged.connect(self._mark_dirty)
        basic_lay.addWidget(self.default_skill_combo)

        lay.addWidget(basic_card)
        lay.addStretch(1)
        return page

    def _build_slots_tab(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 12, 16, 8)
        lay.setSpacing(8)

        self.slots_page = SlotTreeWidget(parent=page)
        self.slots_page.slots_changed.connect(self._mark_dirty)
        self.slots_page.slots_changed.connect(self._refresh_json_preview)
        lay.addWidget(self.slots_page, 1)

        add_btn = PrimaryPushButton(FluentIcon.ADD, "+ 添加段落", page)
        add_btn.setFixedHeight(40)
        add_btn.clicked.connect(self._on_add_slot)
        lay.addWidget(add_btn)
        return page

    def _build_json_tab(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 16, 24, 8)
        lay.setSpacing(8)

        self.json_preview = PlainTextEdit(page)
        self.json_preview.setReadOnly(True)
        self.json_preview.setPlaceholderText("选择模板后显示 JSON 预览 …")
        lay.addWidget(self.json_preview, 1)

        validate_btn = PushButton(FluentIcon.ACCEPT_MEDIUM, "验证模板结构", page)
        validate_btn.setFixedHeight(38)
        validate_btn.clicked.connect(self._validate)
        lay.addWidget(validate_btn)
        return page

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_template(self, path: Path) -> None:
        """Load a template file into the editor."""
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

        self.name_input.setText(tpl.name)
        self.product_input.setText(tpl.product)

        self.default_skill_combo.blockSignals(True)
        try:
            target = tpl.default_skill_id or ""
            idx = 0
            for i in range(self.default_skill_combo.count()):
                if self.default_skill_combo.itemText(i) == target:
                    idx = i; break
            self.default_skill_combo.setCurrentIndex(idx)
        finally:
            self.default_skill_combo.blockSignals(False)

        # blocks
        self.slots_page.load_blocks(tpl.blocks)

        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(True)
        self._refresh_json_preview()

    def is_dirty(self) -> bool:
        return self._dirty

    def save(self) -> bool:
        """Save current state to disk.  Returns True on success."""
        return self._save()

    def clear(self) -> None:
        """Clear the editor (no template loaded state)."""
        self._current_path = None
        self._template_id = ""
        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(False)
        self.json_preview.setPlainText("")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_enabled(self, enabled: bool) -> None:
        self.save_btn.setEnabled(enabled)
        self.pivot.setEnabled(enabled)

    def set_vault_root(self, path: Path | None) -> None:
        """Update vault root used for directory ComboBox in the slot tree."""
        self._vault_root = path
        self.slots_page.set_vault_root(path)

    def set_skill_dir(self, skill_dir: Path | None) -> None:
        """Rebuild the default-skill combo from the given directory.

        Preserves the currently selected skill across the rebuild when
        the file is still present on disk — users invoke this via
        ``showEvent`` whenever the page is re-shown, so skills created
        or renamed from the Skills page surface here without an app
        restart. A missing skill falls back to "（无）".
        """
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

    def _mark_dirty(self, *_) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirty_label.setVisible(True)
        self._refresh_json_preview()

    def _build_template_dict(self) -> dict:
        blocks = self.slots_page.get_blocks()
        skill_text = self.default_skill_combo.currentText()
        default_skill_id = None if skill_text == "（无）" else skill_text
        return {
            "id": self._template_id,
            "name": self.name_input.text().strip(),
            "product": self.product_input.text().strip(),
            "default_skill_id": default_skill_id,
            "blocks": [b.model_dump() for b in blocks],
        }

    def _refresh_json_preview(self) -> None:
        if self._current_path is None:
            return
        try:
            d = self._build_template_dict()
            text = json.dumps(d, ensure_ascii=False, indent=2)
        except Exception as exc:
            text = f"// 当前状态序列化失败: {exc}"
        self.json_preview.setPlainText(text)

    def _validate(self) -> bool:
        if self._current_path is None:
            return False
        try:
            d = self._build_template_dict()
            Template.model_validate(d)
            InfoBar.success(
                "Schema 校验通过", "当前模板结构合法",
                parent=self.window(), position=InfoBarPosition.TOP, duration=3000,
            )
            return True
        except Exception as exc:
            first = str(exc).splitlines()[0]
            InfoBar.error(
                "Schema 校验失败", first,
                parent=self.window(), position=InfoBarPosition.TOP, duration=-1,
            )
            return False

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
        """Append a new empty top-level block to the tree."""
        self.slots_page.add_root_block()
