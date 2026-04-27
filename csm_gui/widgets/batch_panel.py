"""Batch-tab panel: multi-line keyword editor + file import + start button."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit
from .csv_import_wizard import CSVImportWizard
try:
    from qfluentwidgets import CaptionLabel
except ImportError:  # pragma: no cover
    from qfluentwidgets import BodyLabel as CaptionLabel
from qfluentwidgets import (
    BodyLabel, PrimaryPushButton, PushButton, FluentIcon,
)
from ..config import AppConfig
from .generation_form import GenerationForm


class BatchPanel(QWidget):
    request_batch = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        root = QVBoxLayout(self)
        root.addWidget(BodyLabel("关键词列表（每行一个，空行忽略，自动去重）"))

        self.keyword_edit = QPlainTextEdit(self)
        self.keyword_edit.setPlaceholderText("例：\n宠物狗粮推荐\n猫砂怎么选\n...")
        self.keyword_edit.setMinimumHeight(180)
        self.keyword_edit.textChanged.connect(self._schedule_recount)
        root.addWidget(self.keyword_edit)

        self.count_label = CaptionLabel("已识别 0 个关键词（去重后）", self)
        root.addWidget(self.count_label)

        import_row = QHBoxLayout()
        self.import_button = PushButton("从文件导入", self, FluentIcon.FOLDER)
        self.import_button.clicked.connect(self._on_import_clicked)
        import_row.addWidget(self.import_button)
        import_row.addStretch(1)
        root.addLayout(import_row)

        self.form = GenerationForm(config, self)
        self.form.changed.connect(self._refresh_enabled)
        root.addWidget(self.form)

        self.start_button = PrimaryPushButton("开始批量", self, FluentIcon.PLAY)
        self.start_button.clicked.connect(self._emit)
        root.addWidget(self.start_button)
        root.addStretch(1)

        self._recount_timer = QTimer(self)
        self._recount_timer.setSingleShot(True)
        self._recount_timer.setInterval(200)
        self._recount_timer.timeout.connect(self._recount)
        self._refresh_enabled()

    def _schedule_recount(self) -> None:
        self._recount_timer.start()

    def unique_keywords(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for line in self.keyword_edit.toPlainText().splitlines():
            k = line.strip()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    def _recount(self) -> None:
        n = len(self.unique_keywords())
        self.count_label.setText(f"已识别 {n} 个关键词（去重后）")
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        ok = self.form.is_valid() and bool(self.unique_keywords())
        self.start_button.setEnabled(ok)

    def _on_import_clicked(self) -> None:
        dlg = CSVImportWizard(self.window())
        if not dlg.exec():
            return
        keywords = dlg.result_keywords()
        if not keywords:
            return
        # Merge with whatever is already in the editor — users can pipe
        # multiple files in by re-opening the wizard.
        existing = [k.strip() for k in self.keyword_edit.toPlainText().splitlines() if k.strip()]
        merged: list[str] = []
        seen: set[str] = set()
        for k in (*existing, *keywords):
            if k in seen:
                continue
            seen.add(k)
            merged.append(k)
        self.keyword_edit.setPlainText("\n".join(merged))
        self._recount()

    def _emit(self) -> None:
        payload = dict(self.form.payload())
        payload["keywords"] = self.unique_keywords()
        payload["seed"] = self._config.last_seed
        self.request_batch.emit(payload)

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self.form.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(
            (not busy) and self.form.is_valid() and bool(self.unique_keywords())
        )
        self.keyword_edit.setReadOnly(busy)
        self.import_button.setEnabled(not busy)
