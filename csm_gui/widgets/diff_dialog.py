"""Side-by-side / unified diff viewer dialog.

Used for comparing two versions of an article body (e.g. previous polished
output vs the current one). The dialog is intentionally generic — it takes
two strings and two labels and renders a coloured diff, so callers in the
history flow, the export-confirm flow, or anywhere else can reuse it.

Defaults to a unified view (compact + readable on narrow windows). The
``ToggleButton`` flips to a side-by-side layout for closer inspection.
"""
from __future__ import annotations
import difflib
import html

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QStackedWidget, QWidget,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    TextBrowser, MessageBoxBase, SegmentedWidget,
)


# Inline colour tokens — mirror theme.py palette so the diff blends with
# the rest of the app without importing the theme module (this widget is
# also used in tests where the theme isn't loaded).
_COLOR_ADD_BG = "#e8f1eb"   # tinted ink-green wash
_COLOR_ADD_FG = "#1b4d3e"
_COLOR_DEL_BG = "#fbe9e1"   # tinted terracotta wash
_COLOR_DEL_FG = "#7a2f1d"
_COLOR_CTX_FG = "#1e1c19"
_COLOR_HUNK_FG = "rgba(30,28,25,0.45)"


def _esc(s: str) -> str:
    """HTML-escape a line and collapse runs of spaces to &nbsp; so leading
    indentation survives the browser's whitespace folding."""
    return html.escape(s).replace(" ", "&nbsp;")


def _render_unified(left: str, right: str, left_label: str, right_label: str) -> str:
    """Build a coloured unified diff in HTML."""
    lines = list(difflib.unified_diff(
        left.splitlines(),
        right.splitlines(),
        fromfile=left_label,
        tofile=right_label,
        lineterm="",
        n=3,
    ))
    if not lines:
        return f"<p style='color:{_COLOR_HUNK_FG}'>两个版本完全一致。</p>"
    rows: list[str] = []
    for raw in lines:
        if raw.startswith("+++") or raw.startswith("---"):
            rows.append(f"<div style='color:{_COLOR_HUNK_FG}'>{_esc(raw)}</div>")
        elif raw.startswith("@@"):
            rows.append(f"<div style='color:{_COLOR_HUNK_FG};margin-top:6px'>{_esc(raw)}</div>")
        elif raw.startswith("+"):
            rows.append(
                f"<div style='background:{_COLOR_ADD_BG};color:{_COLOR_ADD_FG}'>{_esc(raw)}</div>"
            )
        elif raw.startswith("-"):
            rows.append(
                f"<div style='background:{_COLOR_DEL_BG};color:{_COLOR_DEL_FG}'>{_esc(raw)}</div>"
            )
        else:
            rows.append(f"<div style='color:{_COLOR_CTX_FG}'>{_esc(raw)}</div>")
    return (
        "<div style='font-family: \"Consolas\",\"Cascadia Mono\",monospace;"
        "font-size:12px;line-height:1.55'>"
        + "".join(rows)
        + "</div>"
    )


def _render_side(text: str, opcodes, side: str) -> str:
    """Render one column of a side-by-side diff. ``side`` is 'a' or 'b'."""
    src = text.splitlines()
    add_bg, add_fg = _COLOR_ADD_BG, _COLOR_ADD_FG
    del_bg, del_fg = _COLOR_DEL_BG, _COLOR_DEL_FG
    rows: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if side == "a":
            chunk = src[i1:i2]
            paint = (del_bg, del_fg) if tag in ("delete", "replace") else None
        else:
            chunk = src[j1:j2]
            paint = (add_bg, add_fg) if tag in ("insert", "replace") else None
        for line in chunk:
            if paint:
                bg, fg = paint
                rows.append(f"<div style='background:{bg};color:{fg}'>{_esc(line) or '&nbsp;'}</div>")
            else:
                rows.append(f"<div style='color:{_COLOR_CTX_FG}'>{_esc(line) or '&nbsp;'}</div>")
        # Pad shorter side so both columns line up vertically.
        other_len = (j2 - j1) if side == "a" else (i2 - i1)
        my_len = (i2 - i1) if side == "a" else (j2 - j1)
        for _ in range(max(0, other_len - my_len)):
            rows.append("<div>&nbsp;</div>")
    return (
        "<div style='font-family: \"Consolas\",\"Cascadia Mono\",monospace;"
        "font-size:12px;line-height:1.55'>"
        + "".join(rows)
        + "</div>"
    )


class DiffDialog(MessageBoxBase):
    """Modal diff viewer.

    Parameters
    ----------
    left, right
        The two text bodies to compare. ``left`` is treated as the older
        version, ``right`` as the newer.
    left_label, right_label
        Human-readable labels shown above the columns / in the unified
        header.
    """

    def __init__(
        self,
        *,
        left: str,
        right: str,
        left_label: str = "旧版",
        right_label: str = "新版",
        parent=None,
    ):
        super().__init__(parent)
        self._left = left or ""
        self._right = right or ""
        self._left_label = left_label
        self._right_label = right_label

        self.widget.setMinimumSize(820, 560)

        self.viewLayout.addWidget(SubtitleLabel("版本对比", self))
        meta = CaptionLabel(f"{left_label} → {right_label}", self)
        self.viewLayout.addWidget(meta)

        self.segmented = SegmentedWidget(self)
        self.stack = QStackedWidget(self)

        # Unified view ----------------------------------------------------
        self._unified = TextBrowser(self)
        self._unified.setOpenExternalLinks(False)
        self._unified.setHtml(_render_unified(self._left, self._right,
                                              left_label, right_label))
        self.stack.addWidget(self._unified)

        # Side-by-side view ----------------------------------------------
        side_host = QWidget(self)
        side_lay = QHBoxLayout(side_host)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(8)
        opcodes = difflib.SequenceMatcher(
            None, self._left.splitlines(), self._right.splitlines(),
        ).get_opcodes()
        left_col = self._build_column(left_label, _render_side(self._left, opcodes, "a"))
        right_col = self._build_column(right_label, _render_side(self._right, opcodes, "b"))
        side_lay.addWidget(left_col, 1)
        side_lay.addWidget(right_col, 1)
        self.stack.addWidget(side_host)

        self.segmented.addItem(routeKey="unified", text="统一",
                               onClick=lambda: self.stack.setCurrentIndex(0))
        self.segmented.addItem(routeKey="side", text="并排",
                               onClick=lambda: self.stack.setCurrentIndex(1))
        self.segmented.setCurrentItem("unified")

        self.viewLayout.addWidget(self.segmented)
        self.viewLayout.addWidget(self.stack, 1)

        self.yesButton.setText("关闭")
        self.cancelButton.hide()

    def _build_column(self, label: str, html_body: str) -> QWidget:
        col = QWidget(self)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(BodyLabel(label, col))
        browser = TextBrowser(col)
        browser.setHtml(html_body)
        lay.addWidget(browser, 1)
        return col
