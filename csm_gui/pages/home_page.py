"""Home page — single + batch tabs."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget
from qfluentwidgets import BodyLabel, LineEdit, PrimaryPushButton, FluentIcon, Pivot
from ..config import AppConfig
from ..widgets.generation_form import GenerationForm


class _SingleArticlePanel(QWidget):
    request_generate = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        # Give label→input pairs more breathing room than Qt's default (~6px),
        # so the form feels composed rather than cramped.
        root.setSpacing(14)
        root.addWidget(BodyLabel("关键词"))
        self.keyword_input = LineEdit(self)
        self.keyword_input.setPlaceholderText("例：宠物家庭吸尘器推荐")
        self.keyword_input.textChanged.connect(self._refresh_enabled)
        root.addWidget(self.keyword_input)

        self.form = GenerationForm(config, self)
        self.form.changed.connect(self._refresh_enabled)
        root.addWidget(self.form)

        self.generate_button = PrimaryPushButton("开始生成", self, FluentIcon.PLAY)
        self.generate_button.clicked.connect(self._emit)
        root.addWidget(self.generate_button)
        root.addStretch(1)
        self._refresh_enabled()

    def _refresh_enabled(self):
        ok = self.form.is_valid() and bool(self.keyword_input.text().strip())
        self.generate_button.setEnabled(ok)

    def _emit(self):
        payload = dict(self.form.payload())
        payload["keyword"] = self.keyword_input.text().strip()
        self.request_generate.emit(payload)

    def apply_config(self, cfg: AppConfig) -> None:
        self.form.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled((not busy) and self.form.is_valid()
                                        and bool(self.keyword_input.text().strip()))


class HomePage(QWidget):
    request_generate = pyqtSignal(dict)
    request_batch = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._config = config

        root = QVBoxLayout(self)

        self.pivot = Pivot(self)
        self.stack = QStackedWidget(self)

        self.single_panel = _SingleArticlePanel(config, self)
        self.single_panel.request_generate.connect(self.request_generate.emit)
        self.stack.addWidget(self.single_panel)

        from ..widgets.batch_panel import BatchPanel
        self.batch_panel = BatchPanel(config, self)
        self.batch_panel.request_batch.connect(self.request_batch.emit)
        self.stack.addWidget(self.batch_panel)

        self.pivot.addItem(routeKey="single", text="单篇",
                           onClick=lambda: self.stack.setCurrentIndex(0))
        self.pivot.addItem(routeKey="batch", text="批量",
                           onClick=lambda: self.stack.setCurrentIndex(1))
        self.pivot.setCurrentItem("single")

        root.addWidget(self.pivot)
        root.addWidget(self.stack, 1)

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self.single_panel.apply_config(cfg)
        self.batch_panel.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self.single_panel.set_busy(busy)
        self.batch_panel.set_busy(busy)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.single_panel.form.refresh_templates()
        self.batch_panel.form.refresh_templates()
