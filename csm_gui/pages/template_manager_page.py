"""Template manager page — TemplateListPanel (left) + TemplateEditorPanel (right).

Follows the same top-level pattern as ArticlePage:
  - QWidget root, objectName + transparent background
  - QSplitter with margin=0
  - Sub-panels get setMinimumWidth
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from qfluentwidgets import MessageBox

from ..config import AppConfig
from ..widgets.template_list_panel import TemplateListPanel
from ..widgets.template_editor_panel import TemplateEditorPanel


class TemplateManagerPage(QWidget):
    """Template management page: browse, create, edit, delete templates.

    Follows the same top-level conventions as ArticlePage/HomePage:
      - transparent background
      - QSplitter fills the whole widget (margin=0)
    """

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("TemplateManagerPage")
        self.setStyleSheet("#TemplateManagerPage {background: transparent;}")
        # Cached skill_dir so ``showEvent`` can re-scan it every time
        # the page is brought to front (without needing a config round-trip).
        self._skill_dir: Path | None = None

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.list_panel = TemplateListPanel(splitter)
        self.list_panel.setMinimumWidth(240)
        self.editor_panel = TemplateEditorPanel(splitter)
        self.editor_panel.setMinimumWidth(480)
        splitter.addWidget(self.list_panel)
        splitter.addWidget(self.editor_panel)
        splitter.setSizes([280, 720])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        # ── Wire signals ──────────────────────────────────────────────────
        self.list_panel.template_selected.connect(self._on_template_selected)
        # After save, refresh the list so renamed templates appear with new name
        self.editor_panel.saved.connect(lambda _: self.list_panel.refresh())

        # ── Apply initial config ──────────────────────────────────────────
        self._apply_config(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_config(self, cfg: AppConfig) -> None:
        """Called by MainWindow when settings are saved."""
        self._apply_config(cfg)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_config(self, cfg: AppConfig) -> None:
        """Use config.default_template's parent dir as initial template directory."""
        # 同步资料库根目录到编辑器（用于「浏览资料库」按钮）
        vault_root = Path(cfg.vault_root) if cfg.vault_root else None
        self.editor_panel.set_vault_root(vault_root)
        self._skill_dir = Path(cfg.skill_dir) if cfg.skill_dir else None
        self.editor_panel.set_skill_dir(self._skill_dir)

        if cfg.default_template:
            tpl_path = Path(cfg.default_template)
            tpl_dir = tpl_path.parent
            if tpl_dir.is_dir() and str(tpl_dir) != str(self.list_panel._dir):
                self.list_panel.set_directory(tpl_dir)
                # Try to auto-select the configured template
                if tpl_path.exists():
                    self.list_panel.select_by_path(tpl_path)
                    # Load without triggering dirty-state dialog
                    self.editor_panel.load_template(tpl_path)

    def showEvent(self, event) -> None:
        """Re-scan the skill directory every time the page is shown.

        The Skills page lets users add / rename / delete ``.md`` files
        out of band; without this rescan the template editor's
        "默认 Skill" combo stayed stale until the app restarted.
        """
        super().showEvent(event)
        self.editor_panel.set_skill_dir(self._skill_dir)

    def _on_template_selected(self, path: Path) -> None:
        """Handle list-panel selection; guard against unsaved changes."""
        if self.editor_panel.is_dirty():
            dlg = MessageBox(
                "有未保存的更改",
                "当前模板有未保存的更改，是否保存后再切换？",
                self,
            )
            dlg.yesButton.setText("保存")
            dlg.cancelButton.setText("放弃更改")
            if dlg.exec():
                # User chose save — attempt save; abort switch on failure
                if not self.editor_panel.save():
                    # Restore list selection to current path
                    cur = self.editor_panel._current_path
                    if cur:
                        self.list_panel.select_by_path(cur)
                    return

        self.editor_panel.load_template(path)
