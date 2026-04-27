"""CSV / TXT keyword import wizard.

Replaces BatchPanel's "open file → dump as text" path with a 2-step flow
that gives the user a chance to pick the right column and review the
deduped result before it lands in the keyword editor.

Flow:
1. **来源**     pick file + (CSV only) header / column / delimiter
2. **预览**     parsed rows table + dedup count + manual edit area

Returns a list of keywords on accept; the caller writes them into the
keyword editor.
"""
from __future__ import annotations
import csv
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QFormLayout,
    QFileDialog, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
)
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    LineEdit, ComboBox, CheckBox, PushButton, PrimaryPushButton,
    FluentIcon, MessageBoxBase, InfoBar, InfoBarPosition,
)


_DELIM_LABELS = {
    "auto": "自动识别",
    ",": "逗号 ,",
    ";": "分号 ;",
    "\t": "制表符 ⇥",
    "|": "竖线 |",
}


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _parse_rows(text: str, delim: str, has_header: bool) -> tuple[list[str], list[list[str]]]:
    """Parse CSV text → (headers, rows). Headers are synthetic ('列 1', …)
    when has_header is False."""
    reader = csv.reader(text.splitlines(), delimiter=delim)
    rows = [r for r in reader if r]
    if not rows:
        return ([], [])
    if has_header:
        headers = [c.strip() or f"列 {i+1}" for i, c in enumerate(rows[0])]
        body = rows[1:]
    else:
        n = max(len(r) for r in rows)
        headers = [f"列 {i+1}" for i in range(n)]
        body = rows
    return (headers, body)


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        s = (v or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class CSVImportWizard(MessageBoxBase):
    """Two-step import wizard. Use ``result_keywords()`` after exec()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumSize(640, 560)

        self._keywords: list[str] = []
        self._raw_text: str = ""
        self._is_csv: bool = False

        self._title = SubtitleLabel("导入关键词 — 1 / 2 来源", self)
        self.viewLayout.addWidget(self._title)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_step1())
        self.stack.addWidget(self._build_step2())
        self.viewLayout.addWidget(self.stack, 1)

        self._back_btn = PushButton(FluentIcon.LEFT_ARROW, "上一步", self)
        self._next_btn = PrimaryPushButton(FluentIcon.RIGHT_ARROW, "下一步", self)
        self._back_btn.clicked.connect(self._on_back)
        self._next_btn.clicked.connect(self._on_next)
        nav = QHBoxLayout()
        nav.addWidget(self._back_btn)
        nav.addStretch(1)
        nav.addWidget(self._next_btn)
        self.viewLayout.addLayout(nav)

        self.yesButton.setText("导入")
        self.cancelButton.setText("取消")
        self.yesButton.hide()

        self._refresh_nav()

    # ── Public ────────────────────────────────────────────────────────────
    def result_keywords(self) -> list[str]:
        return list(self._keywords)

    # ── Step 1 ────────────────────────────────────────────────────────────
    def _build_step1(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        pick_row = QHBoxLayout()
        self._path_input = LineEdit(w)
        self._path_input.setPlaceholderText("选择文件 …")
        self._path_input.setReadOnly(True)
        pick_row.addWidget(self._path_input, 1)
        self._browse_btn = PushButton(FluentIcon.FOLDER, "浏览", w)
        self._browse_btn.clicked.connect(self._on_browse)
        pick_row.addWidget(self._browse_btn)
        lay.addLayout(pick_row)

        self._csv_box = QWidget(w)
        form = QFormLayout(self._csv_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._delim_combo = ComboBox(self._csv_box)
        for k, label in _DELIM_LABELS.items():
            self._delim_combo.addItem(label, userData=k)
        self._delim_combo.currentIndexChanged.connect(self._reparse_csv)
        form.addRow(BodyLabel("分隔符"), self._delim_combo)

        self._header_check = CheckBox("首行是表头", self._csv_box)
        self._header_check.setChecked(True)
        self._header_check.toggled.connect(self._reparse_csv)
        form.addRow(BodyLabel(""), self._header_check)

        self._column_combo = ComboBox(self._csv_box)
        form.addRow(BodyLabel("关键词列"), self._column_combo)

        lay.addWidget(self._csv_box)
        self._csv_box.hide()

        self._txt_hint = CaptionLabel("纯文本：每行一个关键词，空行忽略。", w)
        self._txt_hint.setStyleSheet("color: rgba(30,28,25,0.45)")
        lay.addWidget(self._txt_hint)
        self._txt_hint.hide()

        lay.addStretch(1)
        return w

    # ── Step 2 ────────────────────────────────────────────────────────────
    def _build_step2(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(StrongBodyLabel("预览（可手动编辑，每行一个关键词）"))
        self._preview_edit = QPlainTextEdit(w)
        self._preview_edit.setPlaceholderText("…")
        self._preview_edit.textChanged.connect(self._recount)
        lay.addWidget(self._preview_edit, 1)

        self._count_label = CaptionLabel("已识别 0 个关键词（去重后）", w)
        lay.addWidget(self._count_label)
        return w

    # ── Browse + parse ────────────────────────────────────────────────────
    def _on_browse(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "选择关键词文件", filter="文本 (*.txt *.csv);;CSV (*.csv);;TXT (*.txt)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            InfoBar.error("读取失败", str(e), parent=self,
                          position=InfoBarPosition.TOP)
            return
        self._path_input.setText(str(path))
        self._raw_text = text
        self._is_csv = path.suffix.lower() == ".csv"
        self._csv_box.setVisible(self._is_csv)
        self._txt_hint.setVisible(not self._is_csv)
        if self._is_csv:
            sniffed = _sniff_delimiter(text[:2048])
            for i in range(self._delim_combo.count()):
                if self._delim_combo.itemData(i) == sniffed:
                    self._delim_combo.setCurrentIndex(i)
                    break
            self._reparse_csv()

    def _reparse_csv(self) -> None:
        if not (self._is_csv and self._raw_text):
            return
        delim_key = self._delim_combo.currentData() or "auto"
        delim = _sniff_delimiter(self._raw_text[:2048]) if delim_key == "auto" else delim_key
        headers, _ = _parse_rows(self._raw_text, delim, self._header_check.isChecked())
        prev = self._column_combo.currentIndex()
        self._column_combo.clear()
        for h in headers:
            self._column_combo.addItem(h)
        if 0 <= prev < self._column_combo.count():
            self._column_combo.setCurrentIndex(prev)

    # ── Navigation ────────────────────────────────────────────────────────
    def _on_back(self) -> None:
        if self.stack.currentIndex() > 0:
            self.stack.setCurrentIndex(0)
            self._refresh_nav()

    def _on_next(self) -> None:
        i = self.stack.currentIndex()
        if i == 0:
            if not self._raw_text.strip():
                InfoBar.error("尚未选择文件", "请先选择关键词文件",
                              parent=self, position=InfoBarPosition.TOP)
                return
            self._populate_preview()
            self.stack.setCurrentIndex(1)
            self._refresh_nav()

    def _refresh_nav(self) -> None:
        i = self.stack.currentIndex()
        self._title.setText(["导入关键词 — 1 / 2 来源",
                              "导入关键词 — 2 / 2 预览"][i])
        self._back_btn.setEnabled(i > 0)
        is_last = (i == self.stack.count() - 1)
        self._next_btn.setVisible(not is_last)
        self.yesButton.setVisible(is_last)

    def _populate_preview(self) -> None:
        if self._is_csv:
            delim_key = self._delim_combo.currentData() or "auto"
            delim = _sniff_delimiter(self._raw_text[:2048]) if delim_key == "auto" else delim_key
            _, body = _parse_rows(self._raw_text, delim, self._header_check.isChecked())
            col = max(0, self._column_combo.currentIndex())
            values = [r[col] if col < len(r) else "" for r in body]
        else:
            values = self._raw_text.splitlines()
        deduped = _dedup(values)
        self._preview_edit.setPlainText("\n".join(deduped))
        self._recount()

    def _recount(self) -> None:
        n = len(_dedup(self._preview_edit.toPlainText().splitlines()))
        self._count_label.setText(f"已识别 {n} 个关键词（去重后）")

    def accept(self) -> None:  # type: ignore[override]
        self._keywords = _dedup(self._preview_edit.toPlainText().splitlines())
        if not self._keywords:
            InfoBar.error("无可用关键词", "预览结果为空，请检查输入",
                          parent=self, position=InfoBarPosition.TOP)
            return
        super().accept()
