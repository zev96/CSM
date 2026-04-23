"""Win11 Fluent theme — central place to tune app colours.

Edit the constants in this module to retheme the whole app:

* ``PRIMARY_BLUE`` — accent colour for buttons, chevrons, focus rings
* ``PAGE_BG``      — page-content background behind cards / forms
* ``CARD_BG``      — surface colour for CardWidget rows / dialogs

``apply_theme()`` is the single call site in ``app.py``; it installs the
qfluentwidgets theme and a small app-level QSS that paints the page
background. Individual widgets may still override their own background
locally (e.g. the draft editor's white surface, pick-list rows) — those
overrides live in the widget modules, not here.

NO emojis — all icons must use qfluentwidgets.FluentIcon enum values.
"""
from __future__ import annotations
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

PRIMARY_BLUE = QColor("#0067C0")
PAGE_BG = "#f7f8f9"
CARD_BG = "#ffffff"


# Target the FluentWindow's content stack. ``FluentWindow`` / ``StackedWidget``
# cover the main page container; the navigation panel on the left keeps its
# own qfluentwidgets-rendered look because it paints itself rather than
# honouring ``background-color``.
_APP_QSS = f"""
FluentWindow > QWidget,
StackedWidget,
PopUpAniStackedWidget {{
    background-color: {PAGE_BG};
}}
"""


def apply_theme() -> None:
    setTheme(Theme.LIGHT)
    setThemeColor(PRIMARY_BLUE)
    app = QApplication.instance()
    if app is not None:
        # Append rather than overwrite so any existing qss (set by
        # qfluentwidgets' setTheme) is preserved.
        existing = app.styleSheet() or ""
        if _APP_QSS.strip() not in existing:
            app.setStyleSheet(existing + "\n" + _APP_QSS)
