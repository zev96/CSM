"""Settings page — all persistent user preferences."""
from __future__ import annotations
from typing import Callable
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFileDialog, QHBoxLayout
from qfluentwidgets import (
    ComboBox, SpinBox, LineEdit, PasswordLineEdit,
    PrimaryPushButton, PushButton, FluentIcon, SubtitleLabel, BodyLabel, CardWidget,
)
from ..config import AppConfig


class _PathCard(CardWidget):
    """Label + LineEdit + Browse button. `mode` is 'dir' or 'file'."""
    def __init__(self, label: str, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        lay = QHBoxLayout(self)
        lay.addWidget(BodyLabel(label))
        self.input = LineEdit(self)
        self.input.setMinimumWidth(320)
        lay.addWidget(self.input, 1)
        self.btn = PushButton("浏览", self, FluentIcon.FOLDER)
        self.btn.clicked.connect(self._pick)
        lay.addWidget(self.btn)

    def _pick(self):
        if self.mode == "dir":
            p = QFileDialog.getExistingDirectory(self, "选择目录")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "选择文件", filter="JSON (*.json)")
        if p:
            self.input.setText(p)

    def text(self) -> str:
        return self.input.text()

    def setText(self, s: str) -> None:
        self.input.setText(s or "")


class SettingsPage(QWidget):
    def __init__(self, config: AppConfig, on_save: Callable[[AppConfig], None], parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._config = config
        self._on_save = on_save

        root = QVBoxLayout(self)
        root.addWidget(SubtitleLabel("设置"))

        self.vault_card = _PathCard("资料库路径", "dir")
        self.out_card = _PathCard("输出目录", "dir")
        self.template_card = _PathCard("默认模板 (.json)", "file")
        self.skill_card = _PathCard("Skills 目录", "dir")

        self.provider_card = ComboBox(self)
        self.provider_card.addItems(["mock", "anthropic", "deepseek"])

        self.anthropic_key_input = PasswordLineEdit(self)
        self.anthropic_key_input.setPlaceholderText("sk-ant-...")
        self.deepseek_key_input = PasswordLineEdit(self)
        self.deepseek_key_input.setPlaceholderText("sk-...")

        self.seed_card = SpinBox(self)
        self.seed_card.setRange(0, 99999)

        for w in (self.vault_card, self.out_card, self.template_card, self.skill_card):
            root.addWidget(w)
        root.addWidget(BodyLabel("默认 LLM 供应商"))
        root.addWidget(self.provider_card)
        root.addWidget(BodyLabel("Anthropic API Key"))
        root.addWidget(self.anthropic_key_input)
        root.addWidget(BodyLabel("DeepSeek API Key"))
        root.addWidget(self.deepseek_key_input)
        root.addWidget(BodyLabel("默认 seed"))
        root.addWidget(self.seed_card)

        self.save_button = PrimaryPushButton("保存", self)
        self.save_button.clicked.connect(self._save)
        root.addWidget(self.save_button)
        root.addStretch(1)

        # Expose input widgets for tests
        self.vault_input = self.vault_card.input
        self.out_input = self.out_card.input
        self.template_input = self.template_card.input
        self.skill_input = self.skill_card.input

        self._load_from(config)

    def _load_from(self, cfg: AppConfig) -> None:
        self.vault_card.setText(cfg.vault_root or "")
        self.out_card.setText(cfg.out_dir or "")
        self.template_card.setText(cfg.default_template or "")
        self.skill_card.setText(cfg.skill_dir or "")
        idx = self.provider_card.findText(cfg.default_provider)
        if idx >= 0:
            self.provider_card.setCurrentIndex(idx)
        self.anthropic_key_input.setText(cfg.api_keys.get("anthropic", ""))
        self.deepseek_key_input.setText(cfg.api_keys.get("deepseek", ""))
        self.seed_card.setValue(cfg.last_seed)

    def _save(self) -> None:
        new_cfg = AppConfig(
            vault_root=self.vault_card.text() or None,
            out_dir=self.out_card.text() or None,
            default_provider=self.provider_card.currentText(),  # type: ignore[arg-type]
            api_keys={
                "anthropic": self.anthropic_key_input.text(),
                "deepseek": self.deepseek_key_input.text(),
            },
            default_template=self.template_card.text() or None,
            skill_dir=self.skill_card.text() or None,
            last_seed=self.seed_card.value(),
        )
        self._on_save(new_cfg)
