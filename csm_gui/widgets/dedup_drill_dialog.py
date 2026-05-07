"""DedupDrillDialog — modal dialog showing top matches + hit segments."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QDialogButtonBox, QSplitter, QWidget,
)
from qfluentwidgets import StrongBodyLabel, BodyLabel

from csm_core.dedup.report import DuplicateReport

_KIND_LABEL = {"history": "历史重复率", "vault": "素材引用率"}


class DedupDrillDialog(QDialog):
    """Drill-down dialog. Read-only — closed via Close button."""

    open_source_requested = pyqtSignal(str)  # absolute path

    def __init__(self, report: DuplicateReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{_KIND_LABEL.get(report.corpus_kind, '查重')} 详情")
        self.resize(820, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        # Summary
        pct = round(report.duplicate_ratio * 100)
        self.summary_label = BodyLabel(
            f"当前文章共 {report.text_length:,} 字，"
            f"{report.duplicate_chars:,} 字（{pct}%）在语料库找到",
            self,
        )
        root.addWidget(self.summary_label)

        # Splitter: top — matches; bottom — hits
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # Top matches
        top_box = QWidget()
        top_lay = QVBoxLayout(top_box)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(6)
        top_lay.addWidget(StrongBodyLabel("Top 相似文章（双击打开）", top_box))
        self.top_matches_list = QListWidget(top_box)
        self.top_matches_list.itemDoubleClicked.connect(self._on_match_double_clicked)
        for m in report.top_matches:
            it = QListWidgetItem(
                f"《{m.source_title}》 — {m.overlap_chars} 字重叠（{m.overlap_ratio*100:.1f}%）"
            )
            it.setData(Qt.ItemDataRole.UserRole, m.source_path)
            self.top_matches_list.addItem(it)
        top_lay.addWidget(self.top_matches_list)
        splitter.addWidget(top_box)

        # Hits
        bottom_box = QWidget()
        bot_lay = QVBoxLayout(bottom_box)
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(6)
        bot_lay.addWidget(StrongBodyLabel("命中段落（按位置排序）", bottom_box))
        self.hits_list = QListWidget(bottom_box)
        for h in report.hits:
            it = QListWidgetItem(
                f"第 {h.start}–{h.end} 字  来自《{h.source_title}》\n"
                f"  片段：{h.text}\n"
                f"  上下文：{h.source_excerpt}"
            )
            it.setData(Qt.ItemDataRole.UserRole, h.source_path)
            self.hits_list.addItem(it)
        self.hits_list.itemDoubleClicked.connect(self._on_match_double_clicked)
        bot_lay.addWidget(self.hits_list)
        splitter.addWidget(bottom_box)

        splitter.setSizes([220, 320])

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_match_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_source_requested.emit(str(path))
