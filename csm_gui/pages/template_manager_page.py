"""Template manager page — QTabWidget with 模板 and 框架 tabs.

模板 tab:  TemplateListPanel  (left)  + TemplateEditorPanel (right)
框架 tab:  FrameworkListPanel (left)  + FrameworkEditorPanel (right)

Follows the same top-level pattern as ArticlePage:
  - QWidget root, objectName + transparent background
  - QSplitter with margin=0 inside each tab
  - Sub-panels get setMinimumWidth
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QTabWidget
from qfluentwidgets import MessageBox

from ..config import AppConfig
from ..widgets.template_list_panel import TemplateListPanel
from ..widgets.template_editor_panel import TemplateEditorPanel
from ..widgets.framework_list_panel import FrameworkListPanel
from ..widgets.framework_editor_panel import FrameworkEditorPanel


class TemplateManagerPage(QWidget):
    """Template management page: browse, create, edit, delete templates and frameworks.

    Follows the same top-level conventions as ArticlePage/HomePage:
      - transparent background
      - QTabWidget fills the whole widget (margin=0)
    """

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("TemplateManagerPage")
        self.setStyleSheet("#TemplateManagerPage {background: transparent;}")

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("TemplateManagerTabs")

        # --- 模板 tab -------------------------------------------------------
        tpl_tab = QWidget(self.tabs)
        tpl_splitter = QSplitter(Qt.Orientation.Horizontal, tpl_tab)
        self.list_panel = TemplateListPanel(tpl_splitter)
        self.list_panel.setMinimumWidth(240)
        self.editor_panel = TemplateEditorPanel(tpl_splitter)
        self.editor_panel.setMinimumWidth(480)
        tpl_splitter.addWidget(self.list_panel)
        tpl_splitter.addWidget(self.editor_panel)
        tpl_splitter.setSizes([280, 720])
        tpl_layout = QVBoxLayout(tpl_tab)
        tpl_layout.setContentsMargins(0, 0, 0, 0)
        tpl_layout.addWidget(tpl_splitter)
        self.tabs.addTab(tpl_tab, "模板")

        # --- 框架 tab -------------------------------------------------------
        fw_tab = QWidget(self.tabs)
        fw_splitter = QSplitter(Qt.Orientation.Horizontal, fw_tab)
        self.framework_list_panel = FrameworkListPanel(fw_splitter)
        self.framework_list_panel.setMinimumWidth(240)
        self.framework_editor_panel = FrameworkEditorPanel(fw_splitter)
        self.framework_editor_panel.setMinimumWidth(480)
        fw_splitter.addWidget(self.framework_list_panel)
        fw_splitter.addWidget(self.framework_editor_panel)
        fw_splitter.setSizes([280, 720])
        fw_layout = QVBoxLayout(fw_tab)
        fw_layout.setContentsMargins(0, 0, 0, 0)
        fw_layout.addWidget(fw_splitter)
        self.tabs.addTab(fw_tab, "框架")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.tabs)

        # ── Wire signals ──────────────────────────────────────────────────
        self.list_panel.template_selected.connect(self._on_template_selected)
        # After save, refresh the list so renamed templates appear with new name
        self.editor_panel.saved.connect(lambda _: self.list_panel.refresh())

        # Framework signals
        self.framework_list_panel.framework_selected.connect(self._on_framework_selected)
        self.framework_editor_panel.saved.connect(lambda _: self.framework_list_panel.refresh())

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

    def _on_framework_selected(self, path: Path) -> None:
        """Handle framework list-panel selection; guard against unsaved changes."""
        if self.framework_editor_panel.is_dirty():
            dlg = MessageBox(
                "有未保存的更改",
                "当前框架有未保存的更改，是否保存后再切换？",
                self,
            )
            dlg.yesButton.setText("保存")
            dlg.cancelButton.setText("放弃更改")
            if dlg.exec():
                if not self.framework_editor_panel.save():
                    cur = self.framework_editor_panel.current_path()
                    if cur:
                        self.framework_list_panel.select_by_path(cur)
                    return
        self.framework_editor_panel.load_framework(path)
