"""DedupDrillDialog — modal dialog showing top matches + hit segments.

Styled to match the rest of the app's modal flows (warm paper background,
fluent button at the foot, BodyLabel typography). The legacy
``QDialogButtonBox`` Close button looked like a stock Win32 widget against
the rest of the studio chrome — replaced with a fluent ``PushButton``.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QSplitter, QWidget,
)
from qfluentwidgets import StrongBodyLabel, BodyLabel, PushButton

from csm_core.dedup.report import DuplicateReport

_KIND_LABEL = {"history": "历史重复率", "vault": "素材引用率"}

# Tokens — mirror the rest of the studio
_BG     = "#f7f6f2"
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_SURFACE = "#ffffff"


_LIST_QSS = f"""
QListWidget {{
    background: {_SURFACE};
    border: 1px solid {_INK_5};
    border-radius: 8px;
    padding: 4px;
    color: {_INK};
    font-size: 12px;
    outline: 0;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background: rgba(30,28,25,0.04);
}}
QListWidget::item:selected {{
    background: rgba(47,111,94,0.12);
    color: {_INK};
}}
"""


class DedupDrillDialog(QDialog):
    """Drill-down dialog. Read-only — closed via 关闭 button."""

    open_source_requested = pyqtSignal(str)  # absolute path

    def __init__(self, report: DuplicateReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{_KIND_LABEL.get(report.corpus_kind, '查重')} 详情")
        self.resize(820, 560)
        self.setObjectName("DedupDrillDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#DedupDrillDialog {{ background: {_BG}; }}"
            + _LIST_QSS
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # Heading
        head = QVBoxLayout(); head.setSpacing(2); head.setContentsMargins(0, 0, 0, 0)
        title = StrongBodyLabel(
            f"{_KIND_LABEL.get(report.corpus_kind, '查重')} 详情", self,
        )
        title.setStyleSheet(f"color: {_INK}; font-size: 16px; font-weight: 600;")
        head.addWidget(title)

        pct = round(report.duplicate_ratio * 100)
        self.summary_label = BodyLabel(
            f"当前文章共 {report.text_length:,} 字，"
            f"{report.duplicate_chars:,} 字（{pct}%）在语料库找到",
            self,
        )
        self.summary_label.setStyleSheet(
            f"color: {_INK_2}; font-size: 12px; background: transparent;"
        )
        head.addWidget(self.summary_label)
        root.addLayout(head)

        # Splitter: top — matches; bottom — hits
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: transparent; }}"
        )
        root.addWidget(splitter, 1)

        # Top matches
        top_box = QWidget()
        top_box.setStyleSheet("background: transparent;")
        top_lay = QVBoxLayout(top_box)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(6)
        top_eyebrow = self._eyebrow("Top 相似文章 · 双击打开", top_box)
        top_lay.addWidget(top_eyebrow)
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
        bottom_box.setStyleSheet("background: transparent;")
        bot_lay = QVBoxLayout(bottom_box)
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(6)
        bot_eyebrow = self._eyebrow("命中段落 · 按位置排序", bottom_box)
        bot_lay.addWidget(bot_eyebrow)
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

        # Footer button
        foot = QHBoxLayout(); foot.setContentsMargins(0, 0, 0, 0); foot.setSpacing(8)
        foot.addStretch(1)
        self.close_btn = PushButton("关闭", self)
        self.close_btn.setFixedHeight(30)
        self.close_btn.clicked.connect(self.reject)
        foot.addWidget(self.close_btn)
        root.addLayout(foot)

    @staticmethod
    def _eyebrow(text: str, parent) -> StrongBodyLabel:
        lbl = StrongBodyLabel(text, parent)
        lbl.setStyleSheet(
            f"color: {_INK_3}; font-size: 11px; letter-spacing: 0.6px;"
            " font-weight: 600; background: transparent;"
        )
        return lbl

    def _on_match_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_source_requested.emit(str(path))
