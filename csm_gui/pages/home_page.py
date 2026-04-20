"""Home page — keyword + template form, emits request_generate dict."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, LineEdit, PrimaryPushButton, PushButton,
    ComboBox, FluentIcon,
)
from ..config import AppConfig


class HomePage(QWidget):
    request_generate = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._config = config

        root = QVBoxLayout(self)
        root.addWidget(SubtitleLabel("单篇精修"))

        root.addWidget(BodyLabel("关键词"))
        self.keyword_input = LineEdit(self)
        self.keyword_input.setPlaceholderText("例：宠物家庭吸尘器推荐")
        self.keyword_input.textChanged.connect(self._refresh_enabled)
        root.addWidget(self.keyword_input)

        root.addWidget(BodyLabel("模板"))
        row = QHBoxLayout()
        self.template_input = LineEdit(self)
        self.template_input.setText(config.default_template or "")
        self.template_input.textChanged.connect(self._refresh_enabled)
        row.addWidget(self.template_input, 1)
        self.template_browse = PushButton("选择", self, FluentIcon.FOLDER)
        self.template_browse.clicked.connect(self._pick_template)
        row.addWidget(self.template_browse)
        root.addLayout(row)

        root.addWidget(BodyLabel("资料库"))
        self.vault_input = LineEdit(self)
        self.vault_input.setText(config.vault_root or "")
        self.vault_input.textChanged.connect(self._refresh_enabled)
        root.addWidget(self.vault_input)

        root.addWidget(BodyLabel("LLM 供应商"))
        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems(["mock", "anthropic", "deepseek"])
        idx = self.provider_combo.findText(config.default_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        root.addWidget(self.provider_combo)

        self.generate_button = PrimaryPushButton("开始生成", self, FluentIcon.PLAY)
        self.generate_button.clicked.connect(self._emit)
        root.addWidget(self.generate_button)

        root.addStretch(1)
        self._refresh_enabled()

    def _pick_template(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择模板", filter="JSON (*.json)")
        if p:
            self.template_input.setText(p)

    def _refresh_enabled(self):
        ok = bool(
            self.keyword_input.text().strip()
            and self.template_input.text().strip()
            and self.vault_input.text().strip()
        )
        self.generate_button.setEnabled(ok)

    def _emit(self):
        self.request_generate.emit({
            "keyword": self.keyword_input.text().strip(),
            "template_path": self.template_input.text().strip(),
            "vault_root": self.vault_input.text().strip(),
            "provider": self.provider_combo.currentText(),
        })

    def apply_config(self, cfg: AppConfig) -> None:
        """Called by MainWindow after settings are saved."""
        self._config = cfg
        self.template_input.setText(cfg.default_template or self.template_input.text())
        self.vault_input.setText(cfg.vault_root or self.vault_input.text())
        idx = self.provider_combo.findText(cfg.default_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
