"""Template manager — library grid (front) + editor (back).

The library matches ``cms/project/prototype/templates.jsx``: full-width
header, search/tag toolbar, and an auto-fill card grid. Selecting a
card swaps to the editor with a Back button on top; saving from the
editor refreshes the library so renames are reflected immediately.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget
from qfluentwidgets import MessageBox

from ..config import AppConfig
from ..widgets.template_library_panel import TemplateLibraryPanel
from ..widgets.template_editor_panel import TemplateEditorPanel


class TemplateManagerPage(QWidget):
    """Page with two views — library (grid) and editor — swapped via stack."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("TemplateManagerPage")
        self.setStyleSheet("#TemplateManagerPage { background: transparent; }")

        self._skill_dir: Path | None = None

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        # ── View 0: library grid ──────────────────────────────────────────
        self.list_panel = TemplateLibraryPanel(self)
        self._stack.addWidget(self.list_panel)

        # ── View 1: editor (back button lives inside the header card) ────
        editor_view = QWidget(self)
        editor_view.setStyleSheet("background: transparent;")
        ev_lay = QVBoxLayout(editor_view)
        ev_lay.setContentsMargins(28, 18, 28, 18)
        ev_lay.setSpacing(12)
        self.editor_panel = TemplateEditorPanel(editor_view)
        ev_lay.addWidget(self.editor_panel, 1)
        self._stack.addWidget(editor_view)

        # ── Wire ──────────────────────────────────────────────────────────
        self.list_panel.template_selected.connect(self._on_template_selected)
        self.editor_panel.saved.connect(lambda _: self.list_panel.refresh())
        self.editor_panel.back_requested.connect(self._on_back)

        self._apply_config(config)
        self._stack.setCurrentIndex(0)

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────
    def apply_config(self, cfg: AppConfig) -> None:
        self._apply_config(cfg)

    def _apply_config(self, cfg: AppConfig) -> None:
        vault_root = Path(cfg.vault_root) if cfg.vault_root else None
        self.editor_panel.set_vault_root(vault_root)
        self._skill_dir = Path(cfg.skill_dir) if cfg.skill_dir else None
        self.editor_panel.set_skill_dir(self._skill_dir)

        if cfg.default_template:
            tpl_path = Path(cfg.default_template)
            # ``default_template`` is now a directory (new behaviour) but
            # may still be a single .json file in older configs — handle
            # both transparently.
            tpl_dir = tpl_path if tpl_path.is_dir() else tpl_path.parent
            if tpl_dir.is_dir() and (self.list_panel._dir is None
                                      or str(tpl_dir) != str(self.list_panel._dir)):
                self.list_panel.set_directory(tpl_dir)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Skills can be edited out-of-band — refresh combo on every show.
        self.editor_panel.set_skill_dir(self._skill_dir)

    # ──────────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────────
    def _on_template_selected(self, path: Path) -> None:
        if self.editor_panel.is_dirty():
            dlg = MessageBox(
                "有未保存的更改",
                "当前模板有未保存的更改，是否保存后再切换？",
                self,
            )
            dlg.yesButton.setText("保存")
            dlg.cancelButton.setText("放弃更改")
            if dlg.exec():
                if not self.editor_panel.save():
                    return
        self.editor_panel.load_template(path)
        self._stack.setCurrentIndex(1)

    def _on_back(self) -> None:
        if self.editor_panel.is_dirty():
            dlg = MessageBox(
                "有未保存的更改",
                "当前模板有未保存的更改，是否保存后再返回？",
                self,
            )
            dlg.yesButton.setText("保存")
            dlg.cancelButton.setText("放弃更改")
            if dlg.exec() and not self.editor_panel.save():
                return
        self.list_panel.refresh()
        self._stack.setCurrentIndex(0)
