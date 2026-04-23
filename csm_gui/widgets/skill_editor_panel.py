"""Right-side skill editor: name input + plain-text markdown editor + save.

Atomic write (tmp file + replace) and collision-aware rename, matching the
template editor's behaviour. No markdown rendering — skills are prose that
feeds an LLM; what-you-see-is-what-the-model-gets is the right invariant.
"""
from __future__ import annotations
import os
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    StrongBodyLabel, BodyLabel,
    LineEdit, PlainTextEdit, PrimaryPushButton, FluentIcon,
    CardWidget, InfoBar, InfoBarPosition,
)


class SkillEditorPanel(QWidget):
    """Editor for a single skill .md file."""

    saved = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Path | None = None
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        name_card = CardWidget(self)
        name_lay = QVBoxLayout(name_card)
        name_lay.setContentsMargins(16, 12, 16, 12)
        name_lay.setSpacing(6)
        name_lay.addWidget(StrongBodyLabel("Skill"))
        name_lay.addWidget(BodyLabel("名称（保存时重命名文件）"))
        self.name_input = LineEdit(name_card)
        self.name_input.textChanged.connect(self._mark_dirty)
        name_lay.addWidget(self.name_input)
        root.addWidget(name_card)

        edit_card = CardWidget(self)
        edit_lay = QVBoxLayout(edit_card)
        edit_lay.setContentsMargins(16, 12, 16, 12)
        edit_lay.setSpacing(6)
        edit_lay.addWidget(StrongBodyLabel("内容（Markdown）"))
        self.editor = PlainTextEdit(edit_card)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(mono)
        self.editor.textChanged.connect(self._mark_dirty)
        edit_lay.addWidget(self.editor, 1)
        root.addWidget(edit_card, 1)

        bar = QWidget(self)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(16, 8, 16, 8)
        self.dirty_label = BodyLabel("● 有未保存的更改", bar)
        self.dirty_label.setVisible(False)
        bar_lay.addWidget(self.dirty_label)
        bar_lay.addStretch(1)
        self.save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存", bar)
        self.save_btn.setFixedHeight(40)
        self.save_btn.clicked.connect(self.save)
        bar_lay.addWidget(self.save_btn)
        root.addWidget(bar)

        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save)

        self._set_enabled(False)

    def load_skill(self, path: Path) -> None:
        self._current_path = Path(path)
        self.name_input.blockSignals(True)
        self.editor.blockSignals(True)
        try:
            self.name_input.setText(self._current_path.stem)
            self.editor.setPlainText(self._current_path.read_text(encoding="utf-8"))
        finally:
            self.name_input.blockSignals(False)
            self.editor.blockSignals(False)
        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(True)

    def is_dirty(self) -> bool:
        return self._dirty

    def clear(self) -> None:
        self._current_path = None
        self.name_input.clear()
        self.editor.clear()
        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(False)

    def save(self) -> bool:
        if self._current_path is None:
            return False
        new_stem = self.name_input.text().strip()
        if not new_stem:
            InfoBar.error("保存失败", "名称不能为空",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return False

        target = self._current_path.with_name(f"{new_stem}.md")
        if target != self._current_path and target.exists():
            InfoBar.error("保存失败", f"「{new_stem}」已存在",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return False

        tmp = target.with_suffix(".md.tmp")
        tmp.write_text(self.editor.toPlainText(), encoding="utf-8")
        os.replace(tmp, target)
        if target != self._current_path:
            self._current_path.unlink(missing_ok=True)

        self._current_path = target
        self._dirty = False
        self.dirty_label.setVisible(False)
        InfoBar.success("已保存", target.name,
                        parent=self.window(), position=InfoBarPosition.TOP)
        self.saved.emit(target)
        return True

    def _set_enabled(self, enabled: bool) -> None:
        self.save_btn.setEnabled(enabled)
        self.editor.setEnabled(enabled)
        self.name_input.setEnabled(enabled)

    def _mark_dirty(self, *_) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirty_label.setVisible(True)
