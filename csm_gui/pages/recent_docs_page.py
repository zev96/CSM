"""Full history of exported documents.

Lists every entry ``recent_docs.append_export`` has recorded, newest
first. Click a row to reveal the file in the OS file manager (so the
page stays useful even when the file was moved or renamed externally).

Only what the home page hero shows in compact form, with no truncation
and a 'open folder' affordance per row.
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QScrollArea,
)
from qfluentwidgets import PushButton, FluentIcon, ToolButton, MessageBox

from ..recent_docs import RecentDoc, load_recent, relative_when, clear_all

_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT        = "#2f6f5e"
_ACCENT_SOFTER = "#ecf2ee"


def _chip(text: str, variant: str = "outline", parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    palette = {
        "accent": (_ACCENT, _ACCENT_SOFTER),
        "warn":   ("#a26a3a", "#f4e6d6"),
        "outline": (_INK_2, "#ffffff"),
    }
    fg, bg = palette.get(variant, palette["outline"])
    border = "#ffffff" if variant != "outline" else _INK_5
    lbl.setStyleSheet(
        f"color: {fg}; background: {bg}; border: 1px solid {border};"
        " border-radius: 999px; padding: 1px 8px; font-size: 11px;"
    )
    lbl.setFixedHeight(20)
    return lbl


class _RecentRow(QFrame):
    open_requested = pyqtSignal(str)
    reveal_requested = pyqtSignal(str)

    def __init__(self, doc: RecentDoc, parent=None):
        super().__init__(parent)
        self._doc = doc
        self.setObjectName("recentDocsRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#recentDocsRow { background: #ffffff;"
            f" border: 1px solid {_INK_5}; border-radius: 10px; }}"
            "#recentDocsRow:hover { background: #fafaf7; }"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(12)

        title = QLabel(doc.title, self)
        title.setStyleSheet(
            f"color: {_INK}; font-size: 13.5px; font-weight: 500; background: transparent;"
        )
        lay.addWidget(title, 1)

        fmt_label = "Markdown" if doc.fmt == "markdown" else "Word"
        lay.addWidget(_chip(fmt_label, "outline", self))

        when = relative_when(doc.exported_dt)
        meta = QLabel(when, self)
        meta.setStyleSheet(f"color: {_INK_3}; font-size: 11.5px; background: transparent;")
        lay.addWidget(meta)

        status_variant = {"已发布": "accent", "归档": "outline", "草稿": "warn"}
        lay.addWidget(_chip(doc.status, status_variant.get(doc.status, "outline"), self))

        path_btn = ToolButton(FluentIcon.FOLDER, self)
        path_btn.setFixedSize(26, 26)
        path_btn.setToolTip("在文件夹中显示")
        path_btn.clicked.connect(lambda: self.reveal_requested.emit(doc.path))
        lay.addWidget(path_btn)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self._doc.path)
        super().mousePressEvent(ev)


class RecentDocsPage(QWidget):
    """Full-screen list of every recorded export."""

    back_requested = pyqtSignal()
    cleared = pyqtSignal()  # fired after the user confirms 清空列表

    def __init__(self, config_dir: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("recentDocsPage")
        self._config_dir = Path(config_dir)
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22); root.setSpacing(14)

        # Top bar
        bar = QHBoxLayout(); bar.setSpacing(10)
        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "返回主页", self)
        self.back_btn.setFixedHeight(30)
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.back_btn)
        bar.addStretch(1)
        self.clear_btn = PushButton(FluentIcon.DELETE, "清空列表", self)
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        title = QLabel("最近的文档", self)
        title.setStyleSheet(f"color: {_INK}; font-size: 22px; font-weight: 600; background: transparent;")
        root.addWidget(title)
        sub = QLabel("按导出时间倒序排列 · 点击行可打开文件，文件夹按钮在资源管理器中显示", self)
        sub.setStyleSheet(f"color: {_INK_2}; font-size: 12.5px; background: transparent;")
        root.addWidget(sub)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        host = QWidget(); host.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(host)
        self._list_lay.setContentsMargins(0, 4, 0, 4); self._list_lay.setSpacing(8)
        self._list_lay.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self._host = host

        self.refresh()

    def refresh(self) -> None:
        # Clear existing rows.
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None); w.deleteLater()
        docs = load_recent(self._config_dir)
        if not docs:
            empty = QLabel("尚无导出记录 — 在创作区生成并导出一篇即可。", self)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color: {_INK_3}; font-size: 12.5px; padding: 60px 0; background: transparent;"
            )
            self._list_lay.insertWidget(0, empty)
            return
        for doc in docs:
            row = _RecentRow(doc, self._host)
            row.open_requested.connect(self._open_path)
            row.reveal_requested.connect(self._reveal_path)
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)

    def _on_clear_clicked(self) -> None:
        """Confirm + wipe the recent-exports JSON. Files on disk are kept."""
        if not load_recent(self._config_dir):
            return
        dlg = MessageBox(
            "清空最近文档列表",
            "将清空全部历史记录（仅清除列表，已导出的文件不会被删除）。是否继续？",
            self.window(),
        )
        dlg.yesButton.setText("清空")
        dlg.cancelButton.setText("取消")
        if not dlg.exec():
            return
        clear_all(self._config_dir)
        self.refresh()
        self.cleared.emit()

    def _open_path(self, path: str) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass

    def _reveal_path(self, path: str) -> None:
        p = Path(path)
        target = str(p.parent if p.exists() else p.parent)
        try:
            if sys.platform.startswith("win"):
                if p.exists():
                    subprocess.Popen(["explorer", "/select,", str(p)])
                else:
                    os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(p)] if p.exists() else ["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except OSError:
            pass
