"""Shared template/vault/provider form for single + batch tabs."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import BodyLabel, LineEdit, PushButton, ComboBox, FluentIcon
from ..config import AppConfig


class GenerationForm(QWidget):
    changed = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(BodyLabel("模板"))
        row = QHBoxLayout()
        self.template_input = LineEdit(self)
        self.template_input.setText(config.default_template or "")
        self.template_input.textChanged.connect(self.changed.emit)
        row.addWidget(self.template_input, 1)
        self.template_browse = PushButton("选择", self, FluentIcon.FOLDER)
        self.template_browse.clicked.connect(self._pick_template)
        row.addWidget(self.template_browse)
        root.addLayout(row)

        root.addWidget(BodyLabel("资料库"))
        self.vault_input = LineEdit(self)
        self.vault_input.setText(config.vault_root or "")
        self.vault_input.textChanged.connect(self.changed.emit)
        root.addWidget(self.vault_input)

        root.addWidget(BodyLabel("LLM 供应商"))
        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems(["mock", "anthropic", "deepseek"])
        idx = self.provider_combo.findText(config.default_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        root.addWidget(self.provider_combo)

    def _pick_template(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择模板", filter="JSON (*.json)")
        if p:
            self.template_input.setText(p)

    def apply_config(self, cfg: AppConfig) -> None:
        self.template_input.setText(cfg.default_template or "")
        self.vault_input.setText(cfg.vault_root or "")
        idx = self.provider_combo.findText(cfg.default_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

    def is_valid(self) -> bool:
        return bool(
            self.template_input.text().strip()
            and self.vault_input.text().strip()
        )

    def payload(self) -> dict:
        return {
            "template_path": self.template_input.text().strip(),
            "vault_root": self.vault_input.text().strip(),
            "provider": self.provider_combo.currentText(),
        }
