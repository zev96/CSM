"""Bottom action bar for ArticlePage.

A horizontal strip pinned below the markdown preview. Exposes the polish skill
picker and three action buttons (重新随机 / 润色 / 导出). Seed, brand-count and
provider controls were removed: seed comes from config, brand-count falls back
to the template default, and the provider is whatever ``AppConfig.default_provider``
says — the article workspace is not the place to override those ad-hoc.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    PushButton,
    PrimaryPushButton,
    FluentIcon,
)


class ControlsPanel(QWidget):
    # Signal payloads:
    #   rerun_all_requested() — re-randomize every slot with a fresh seed
    #   polish_requested(skill_path: Path | None)
    #   export_requested()
    #   clear_all_requested() — reset the workspace to its initial empty state
    rerun_all_requested = pyqtSignal()
    polish_requested = pyqtSignal(object)
    export_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()

    def __init__(self, skill_dir: Path | None, provider_default: str = "", parent=None):
        # ``provider_default`` is accepted for backwards compatibility with
        # callers that still pass it, but ignored — the provider is read from
        # AppConfig when the polish request is dispatched.
        super().__init__(parent)
        self.setObjectName("ControlsPanel")
        self._skill_dir = Path(skill_dir) if skill_dir else None

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        root.addWidget(BodyLabel("润色风格", self))
        self.skill_combo = ComboBox(self)
        self.skill_combo.setMinimumWidth(200)
        self._populate_skills()
        root.addWidget(self.skill_combo)

        root.addStretch(1)

        self.clear_all_button = PushButton(FluentIcon.DELETE, "清空全部", self)
        self.rerun_all_button = PushButton(FluentIcon.SYNC, "重新随机", self)
        self.polish_button = PrimaryPushButton(FluentIcon.EDIT, "润色", self)
        self.export_button = PushButton(FluentIcon.SAVE, "导出", self)

        root.addWidget(self.clear_all_button)
        root.addWidget(self.rerun_all_button)
        root.addWidget(self.polish_button)
        root.addWidget(self.export_button)

        self.clear_all_button.clicked.connect(self.clear_all_requested.emit)
        self.rerun_all_button.clicked.connect(self.rerun_all_requested.emit)
        self.polish_button.clicked.connect(self._emit_polish)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_skill_dir(self, skill_dir: Path | None) -> None:
        """Repoint at a new skill directory and rebuild the combo."""
        self._skill_dir = Path(skill_dir) if skill_dir else None
        self.skill_combo.clear()
        self._populate_skills()

    def set_provider_default(self, name: str) -> None:
        """Deprecated no-op — provider is read from AppConfig at polish time.

        Kept so that ``ArticlePage.apply_config`` can call through without
        caring about which widgets still surface a provider picker.
        """
        return

    def _populate_skills(self) -> None:
        self.skill_combo.addItem("无")
        if self._skill_dir and self._skill_dir.is_dir():
            stems = sorted(p.stem for p in self._skill_dir.glob("*.md"))
            for name in stems:
                self.skill_combo.addItem(name)

    def _emit_polish(self) -> None:
        name = self.skill_combo.currentText()
        skill_path: Path | None
        if name and name != "无" and self._skill_dir:
            skill_path = self._skill_dir / f"{name}.md"
        else:
            skill_path = None
        self.polish_requested.emit(skill_path)
