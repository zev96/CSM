"""First-run welcome screen.

A full-window page shown the very first time the app launches. The user
fills in 姓名 (required) and 负责产品线 (optional), then clicks the
circular arrow button to enter the home page.

Visual: warm paper background (matches the app's `#f7f6f2`), centered
column with two minimal pill inputs and a black-outline arrow button.
The button stays disabled until the name field has content; on submit
the widget emits ``submitted(name, product)``.

Subsequent edits (avatar / settings page) use the legacy modal
``AccountDialog`` — this widget is only for first launch.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)


# ── Tokens ────────────────────────────────────────────────────────────
_BG     = "#f7f6f2"   # warm paper background — matches MainWindow custom bg
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_5  = "rgba(30,28,25,0.08)"
_INK_DISABLED = "rgba(30,28,25,0.30)"


_INPUT_QSS = """
QLineEdit#FRWInput {
    background: #ffffff;
    border: 1px solid rgba(30,28,25,0.10);
    border-radius: 22px;
    padding: 10px 18px;
    font-size: 14px;
    color: #1e1c19;
    selection-background-color: rgba(47,111,94,0.25);
}
QLineEdit#FRWInput:focus {
    border-color: #2f6f5e;
    background: #ffffff;
}
"""


_ARROW_QSS_ENABLED = """
QPushButton#FRWArrow {
    background: transparent;
    border: 2px solid #1e1c19;
    border-radius: 22px;
    color: #1e1c19;
    font-size: 18px;
    font-weight: 600;
    padding-bottom: 2px;
}
QPushButton#FRWArrow:hover {
    background: #1e1c19;
    color: #ffffff;
}
"""

_ARROW_QSS_DISABLED = """
QPushButton#FRWArrow {
    background: transparent;
    border: 2px solid rgba(30,28,25,0.25);
    border-radius: 22px;
    color: rgba(30,28,25,0.30);
    font-size: 18px;
    font-weight: 600;
    padding-bottom: 2px;
}
"""


class FirstRunWelcome(QWidget):
    """Full-window first-run welcome screen."""

    submitted = pyqtSignal(str, object)  # (name, product_or_None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FirstRunWelcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Solid bg so anything underneath (sidebar, title bar) is fully
        # masked while this overlay is visible.
        self.setStyleSheet(
            f"#FirstRunWelcome {{ background: {_BG}; }}"
            + _INPUT_QSS
        )

        # Outer layout — three rows: top stretch, centered form, bottom
        # stretch. Mirrors the reference image (form sits roughly at the
        # vertical center, slightly above middle).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addStretch(3)

        # The form column has a fixed max width regardless of window size.
        form_row = QHBoxLayout()
        form_row.setContentsMargins(0, 0, 0, 0)
        form_row.addStretch(1)

        self._form = QWidget(self)
        self._form.setFixedWidth(260)
        self._form.setStyleSheet("background: transparent;")
        flay = QVBoxLayout(self._form)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(10)

        # 姓名
        name_label = QLabel("姓名", self._form)
        name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name_label.setStyleSheet(
            f"color: {_INK}; font-size: 13px; font-weight: 600;"
            " background: transparent;"
        )
        flay.addWidget(name_label)

        self.name_input = QLineEdit(self._form)
        self.name_input.setObjectName("FRWInput")
        self.name_input.setFixedHeight(44)
        self.name_input.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name_input.textChanged.connect(self._refresh_arrow_state)
        flay.addWidget(self.name_input)

        flay.addSpacing(8)

        # 负责产品线
        product_label = QLabel("负责产品线", self._form)
        product_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        product_label.setStyleSheet(
            f"color: {_INK}; font-size: 13px; font-weight: 600;"
            " background: transparent;"
        )
        flay.addWidget(product_label)

        self.product_input = QLineEdit(self._form)
        self.product_input.setObjectName("FRWInput")
        self.product_input.setFixedHeight(44)
        self.product_input.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        # Enter on either field submits when valid.
        self.product_input.returnPressed.connect(self._try_submit)
        self.name_input.returnPressed.connect(self._try_submit)
        flay.addWidget(self.product_input)

        flay.addSpacing(20)

        # 圆形箭头按钮
        arrow_row = QHBoxLayout()
        arrow_row.setContentsMargins(0, 0, 0, 0)
        arrow_row.addStretch(1)
        self.arrow_btn = QPushButton("→", self._form)
        self.arrow_btn.setObjectName("FRWArrow")
        self.arrow_btn.setFixedSize(44, 44)
        self.arrow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.arrow_btn.clicked.connect(self._try_submit)
        arrow_row.addWidget(self.arrow_btn)
        arrow_row.addStretch(1)
        flay.addLayout(arrow_row)

        form_row.addWidget(self._form)
        form_row.addStretch(1)
        outer.addLayout(form_row)

        outer.addStretch(4)

        # Initial state.
        self._refresh_arrow_state()
        # Defer focus until the widget is shown so it actually lands in
        # the input (focus-before-show is dropped on Windows).
        self.name_input.setFocus()

    # ── Behaviour ─────────────────────────────────────────────────────
    def _refresh_arrow_state(self) -> None:
        ok = bool(self.name_input.text().strip())
        self.arrow_btn.setEnabled(ok)
        self.arrow_btn.setStyleSheet(
            _ARROW_QSS_ENABLED if ok else _ARROW_QSS_DISABLED
        )
        self.arrow_btn.setToolTip("" if ok else "请先填写姓名")

    def _try_submit(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.name_input.setFocus()
            return
        product = self.product_input.text().strip() or None
        self.submitted.emit(name, product)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        # On first show, drop the cursor in the name field.
        self.name_input.setFocus()

    def keyPressEvent(self, ev):  # noqa: N802
        # Block Esc — first-run is a hard gate.
        if ev.key() == Qt.Key.Key_Escape:
            ev.ignore()
            return
        super().keyPressEvent(ev)
