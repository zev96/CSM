"""Right-hand action/settings panel for ArticlePage.

Provides seed, brand-count, provider and skill controls plus action buttons
(rerun / polish / export). All user interactions are surfaced as Qt signals
so MainWindow can wire them up to pipeline workers.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    SubtitleLabel,
    BodyLabel,
    SpinBox,
    ComboBox,
    PushButton,
    PrimaryPushButton,
    FluentIcon,
)


class ControlsPanel(QWidget):
    rerun_all_requested = pyqtSignal(int, dict)
    polish_requested = pyqtSignal(str, object)
    export_requested = pyqtSignal()

    def __init__(self, skill_dir: Path | None, provider_default: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ControlsPanel")
        self._skill_dir = Path(skill_dir) if skill_dir else None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(SubtitleLabel("控制", self))

        root.addWidget(BodyLabel("随机种子", self))
        self.seed_input = SpinBox(self)
        self.seed_input.setRange(0, 99999)
        self.seed_input.setValue(0)
        root.addWidget(self.seed_input)

        root.addWidget(BodyLabel("品牌竞品数量", self))
        self.brand_count_input = SpinBox(self)
        self.brand_count_input.setRange(1, 9)
        self.brand_count_input.setValue(2)
        root.addWidget(self.brand_count_input)

        root.addWidget(BodyLabel("模型提供商", self))
        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems(["mock", "anthropic", "deepseek"])
        idx = self.provider_combo.findText(provider_default)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        root.addWidget(self.provider_combo)

        root.addWidget(BodyLabel("润色风格 (skill)", self))
        self.skill_combo = ComboBox(self)
        self._populate_skills()
        root.addWidget(self.skill_combo)

        root.addStretch(1)

        self.rerun_all_button = PushButton(FluentIcon.SYNC, "重跑全部", self)
        self.polish_button = PrimaryPushButton(FluentIcon.EDIT, "润色", self)
        self.export_button = PushButton(FluentIcon.SAVE, "导出", self)

        btns = QHBoxLayout()
        btns.addWidget(self.rerun_all_button)
        btns.addWidget(self.polish_button)
        btns.addWidget(self.export_button)
        root.addLayout(btns)

        self.rerun_all_button.clicked.connect(self._emit_rerun)
        self.polish_button.clicked.connect(self._emit_polish)
        self.export_button.clicked.connect(self.export_requested.emit)

    def _populate_skills(self) -> None:
        self.skill_combo.addItem("无")
        if self._skill_dir and self._skill_dir.is_dir():
            stems = sorted(p.stem for p in self._skill_dir.glob("*.md"))
            for name in stems:
                self.skill_combo.addItem(name)

    def _emit_rerun(self) -> None:
        seed = int(self.seed_input.value())
        user_config = {"brand_competitors": int(self.brand_count_input.value())}
        self.rerun_all_requested.emit(seed, user_config)

    def _emit_polish(self) -> None:
        provider = self.provider_combo.currentText()
        name = self.skill_combo.currentText()
        skill_path: Path | None
        if name and name != "无" and self._skill_dir:
            skill_path = self._skill_dir / f"{name}.md"
        else:
            skill_path = None
        self.polish_requested.emit(provider, skill_path)
