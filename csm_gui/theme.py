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
from pathlib import Path
from PyQt6.QtGui import QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

PRIMARY_BLUE = QColor("#2394F2")   # 按钮、chevron、焦点环的主色
PAGE_BG      = "#F6F6F6"           # 页面内容区背景（卡片后面的底色）
CARD_BG      = "#ffffff"           # 卡片 / 对话框表面

# OPPO Sans 4.0 — bundled brand font. Shipped under ``csm_gui/assets/fonts``
# so the repo is self-contained; loaded at startup and installed as the
# application-wide default family. Size stays at Qt's platform default
# (roughly 9pt on Windows) so existing widgets keep their intended
# proportions — we're only swapping the family.
_FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "OPPOSans-4.0.ttf"
_FALLBACK_FAMILIES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")

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


def _install_font() -> str | None:
    """Register OPPO Sans with Qt's font DB and return the family name.

    Returns ``None`` if the font file is missing or Qt rejects it — the
    caller falls back to system defaults so the app still starts.
    """
    if not _FONT_PATH.is_file():
        return None
    font_id = QFontDatabase.addApplicationFont(str(_FONT_PATH))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else None


def apply_theme() -> None:
    setTheme(Theme.LIGHT)
    setThemeColor(PRIMARY_BLUE)
    app = QApplication.instance()
    if app is not None:
        family = _install_font()
        # Build a font stack with OPPO Sans first, then sensible CJK/latin
        # fallbacks. Qt falls through the list per glyph when the primary
        # family lacks coverage.
        families = [family] if family else []
        families.extend(_FALLBACK_FAMILIES)
        font = QFont()
        font.setFamilies(families)
        app.setFont(font)
        # Append rather than overwrite so any existing qss (set by
        # qfluentwidgets' setTheme) is preserved.
        existing = app.styleSheet() or ""
        if _APP_QSS.strip() not in existing:
            app.setStyleSheet(existing + "\n" + _APP_QSS)
