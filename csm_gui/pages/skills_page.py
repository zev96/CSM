"""Top-level Skills management page — list + editor, wired up."""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import MessageBox

from ..config import AppConfig
from ..widgets.skill_list_panel import SkillListPanel
from ..widgets.skill_editor_panel import SkillEditorPanel


class SkillsPage(QWidget):
    """Two-column page: directory-scoped list on the left, editor on the right."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("skillsPage")
        self._config = config

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.list_panel = SkillListPanel(self)
        self.list_panel.setFixedWidth(280)
        self.list_panel.skill_selected.connect(self._on_skill_selected)
        root.addWidget(self.list_panel)

        self.editor_panel = SkillEditorPanel(self)
        self.editor_panel.saved.connect(self._on_saved)
        root.addWidget(self.editor_panel, 1)

        if config.skill_dir:
            self.list_panel.set_directory(Path(config.skill_dir))

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        if cfg.skill_dir:
            self.list_panel.set_directory(Path(cfg.skill_dir))
        else:
            self.editor_panel.clear()

    def _on_skill_selected(self, path: Path) -> None:
        if self.editor_panel.is_dirty():
            decision = self._resolve_dirty()
            if decision == "cancel":
                return
            if decision == "save":
                if not self.editor_panel.save():
                    return
        self.editor_panel.load_skill(path)

    def _on_saved(self, path: Path) -> None:
        self.list_panel.refresh()

    def _resolve_dirty(self) -> str:
        """Prompt on unsaved changes. Returns one of: 'save', 'discard', 'cancel'.
        Override in tests via monkeypatch."""
        dlg = MessageBox(
            "未保存的更改",
            "当前 Skill 有未保存的改动。是否保存？",
            self.window(),
        )
        dlg.yesButton.setText("保存")
        dlg.cancelButton.setText("丢弃")
        if dlg.exec():
            return "save"
        return "discard"
