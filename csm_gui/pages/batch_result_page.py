"""Batch progress + result page (not in left-nav)."""
from __future__ import annotations
import os
from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel, ProgressBar, PushButton, PrimaryPushButton, FluentIcon,
)
from csm_core.batch.report import BatchReport, BatchItem


class BatchResultPage(QWidget):
    cancel_requested = pyqtSignal()
    return_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchResultPage")
        self._batch_dir: str | None = None

        root = QVBoxLayout(self)
        self.header_title = SubtitleLabel("批量生成")
        root.addWidget(self.header_title)
        self.header_meta = CaptionLabel("")
        root.addWidget(self.header_meta)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.current_label = BodyLabel("")
        root.addWidget(self.current_label)

        lists_row = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(BodyLabel("成功"))
        self.success_list = QListWidget(self)
        left_col.addWidget(self.success_list)
        right_col = QVBoxLayout()
        right_col.addWidget(BodyLabel("失败"))
        self.failed_list = QListWidget(self)
        right_col.addWidget(self.failed_list)
        lists_row.addLayout(left_col)
        lists_row.addLayout(right_col)
        root.addLayout(lists_row, 1)

        btn_row = QHBoxLayout()
        self.open_button = PushButton("打开批次目录", self, FluentIcon.FOLDER)
        self.open_button.clicked.connect(self._open_batch_dir)
        btn_row.addWidget(self.open_button)
        btn_row.addStretch(1)
        self.cancel_button = PushButton("取消", self)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.cancel_button)
        self.return_button = PrimaryPushButton("返回", self)
        self.return_button.clicked.connect(self.return_requested.emit)
        self.return_button.setEnabled(False)
        self.return_button.setVisible(False)
        btn_row.addWidget(self.return_button)
        root.addLayout(btn_row)

    def on_batch_started(self, report: BatchReport) -> None:
        self._batch_dir = report.batch_dir
        self.success_list.clear()
        self.failed_list.clear()
        self.progress_bar.setRange(0, max(report.total, 1))
        self.progress_bar.setValue(0)
        self.current_label.setText("")
        self.header_meta.setText(
            f"批次 {report.batch_id}  模板 {Path(report.template_path).name}  "
            f"vault {Path(report.vault_root).name}  种子 {report.seed}"
        )
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("取消")
        self.cancel_button.setVisible(True)
        self.return_button.setEnabled(False)
        self.return_button.setVisible(False)

    def on_batch_progress(self, done: int, total: int, keyword: str) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        if keyword:
            self.current_label.setText(f"当前：{keyword}")

    def on_item_finished(self, item: BatchItem) -> None:
        if item.status == "success":
            self.success_list.addItem(f"✓ {item.keyword}")
        else:
            text = f"⚠ {item.keyword}\n    {item.error_type}: {item.error_message}"
            self.failed_list.addItem(text)

    def on_batch_completed(self, report: BatchReport) -> None:
        self._finalize(report, cancelled=False)

    def on_batch_cancelled(self, report: BatchReport) -> None:
        self._finalize(report, cancelled=True)

    def _finalize(self, report: BatchReport, cancelled: bool) -> None:
        self.progress_bar.setValue(self.progress_bar.maximum() if not cancelled else self.progress_bar.value())
        self.current_label.setText(
            "已取消" if cancelled else f"完成：成功 {self.success_list.count()} / 失败 {self.failed_list.count()}"
        )
        self.cancel_button.setVisible(False)
        self.return_button.setVisible(True)
        self.return_button.setEnabled(True)

    def _on_cancel_clicked(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("取消中…")
        self.cancel_requested.emit()

    def _open_batch_dir(self) -> None:
        if self._batch_dir:
            try:
                os.startfile(self._batch_dir)  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass
