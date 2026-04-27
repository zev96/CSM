"""Ink-green editorial theme — central place to tune app colours.

The palette follows the Claude-Design prototype handoff (墨绿 · 赤陶 · 暖纸色):

* ``PRIMARY_INK_GREEN`` — primary accent (buttons, chevrons, focus rings)
* ``EXPORT_TERRACOTTA``  — reserved exclusively for the Export button so it
  stays visually loud among other actions
* ``PAGE_BG``            — warm paper background behind cards / forms
* ``SURFACE_BG``         — secondary surface (sidebar, raised rows)
* ``CARD_BG``            — clean white card surface

``apply_theme()`` is the single call site in ``app.py``; it installs the
qfluentwidgets theme tokens and a global QSS that paints the page
background, sidebar, cards, inputs, scrollbars and action buttons.

NO emojis — all icons must use qfluentwidgets.FluentIcon enum values.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtGui import QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

# ─── Palette (mirrors prototype/theme.css) ──────────────────────────────
PRIMARY_INK_GREEN = QColor("#2f6f5e")
EXPORT_TERRACOTTA = "#c96442"
EXPORT_TERRACOTTA_HOVER = "#b55734"
EXPORT_TERRACOTTA_SOFT = "#f4e0d5"
ACCENT_SOFT = "#dde9e3"
ACCENT_SOFTER = "#ecf2ee"

PAGE_BG = "#f7f6f2"        # 暖纸色 — 页面内容区底色
SURFACE_BG = "#faf8f3"     # 次级表面 — 侧栏、hover 行
CARD_BG = "#ffffff"        # 卡片表面
INK = "#1e1c19"
INK_2 = "rgba(30,28,25,0.62)"
INK_3 = "rgba(30,28,25,0.38)"
INK_5 = "rgba(30,28,25,0.08)"
WARN = "#b58a2b"
DANGER = "#b04a3a"

# Kept for backward compatibility with any module still importing the old
# name; points at the new primary.
PRIMARY_BLUE = PRIMARY_INK_GREEN

# OPPO Sans 4.0 — bundled brand font. Loaded at startup; Qt font DB falls
# through the family list per glyph when the primary family lacks coverage
# (e.g. emoji glyphs never fire because we avoid emoji entirely).
_FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "OPPOSans-4.0.ttf"
_FALLBACK_FAMILIES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")

_APP_QSS = f"""
/* ── Window chrome + page background ─────────────────────────────── */
FluentWindow,
FluentWindow > QWidget,
StackedWidget,
PopUpAniStackedWidget {{
    background-color: {PAGE_BG};
}}

/* Title bar (top strip with min/max/close + back button) — paint to
   match the warm paper bg so the default Mica/Aero tint disappears. */
FluentTitleBar,
TitleBar {{
    background-color: {PAGE_BG};
    border-bottom: 1px solid {INK_5};
}}
FluentTitleBar > QLabel,
FluentTitleBar > CaptionLabel {{
    color: {INK_2};
    background-color: transparent;
}}

/* ── Navigation panel (sidebar) ──────────────────────────────────── */
NavigationInterface,
NavigationPanel {{
    background-color: {SURFACE_BG};
    border-right: 1px solid {INK_5};
}}

/* ── Cards ───────────────────────────────────────────────────────── */
CardWidget, ElevatedCardWidget, SimpleCardWidget, HeaderCardWidget {{
    background-color: {CARD_BG};
    border: 1px solid {INK_5};
    border-radius: 12px;
}}

/* ── Inputs ──────────────────────────────────────────────────────── */
LineEdit, TextEdit, PlainTextEdit, SearchLineEdit, EditableComboBox, ComboBox,
SpinBox, DoubleSpinBox {{
    background-color: {CARD_BG};
    border: 1px solid {INK_5};
    border-radius: 8px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
}}
LineEdit:focus, TextEdit:focus, PlainTextEdit:focus, SearchLineEdit:focus,
EditableComboBox:focus, ComboBox:focus, SpinBox:focus, DoubleSpinBox:focus {{
    border: 1px solid {PRIMARY_INK_GREEN.name()};
}}

/* ── Buttons ─────────────────────────────────────────────────────── */
PushButton, ToolButton, HyperlinkButton, TransparentPushButton,
TransparentToolButton {{
    border-radius: 8px;
}}
PrimaryPushButton {{
    background-color: {PRIMARY_INK_GREEN.name()};
    border: 1px solid {PRIMARY_INK_GREEN.name()};
    border-radius: 8px;
    color: #ffffff;
}}
PrimaryPushButton:hover {{
    background-color: #3b8a74;
    border: 1px solid #3b8a74;
}}
PrimaryPushButton:pressed {{
    background-color: #265a4c;
    border: 1px solid #265a4c;
}}

/* ── Export button — terracotta accent, set objectName="exportButton" */
QPushButton#exportButton,
PrimaryPushButton#exportButton,
PushButton#exportButton {{
    background-color: {EXPORT_TERRACOTTA};
    border: 1px solid {EXPORT_TERRACOTTA};
    border-radius: 8px;
    color: #ffffff;
    padding: 6px 18px;
    font-weight: 600;
}}
QPushButton#exportButton:hover,
PrimaryPushButton#exportButton:hover,
PushButton#exportButton:hover {{
    background-color: {EXPORT_TERRACOTTA_HOVER};
    border: 1px solid {EXPORT_TERRACOTTA_HOVER};
}}
QPushButton#exportButton:pressed,
PrimaryPushButton#exportButton:pressed,
PushButton#exportButton:pressed {{
    background-color: #9a4a2a;
    border: 1px solid #9a4a2a;
}}
QPushButton#exportButton:disabled,
PrimaryPushButton#exportButton:disabled,
PushButton#exportButton:disabled {{
    background-color: {EXPORT_TERRACOTTA_SOFT};
    border: 1px solid {EXPORT_TERRACOTTA_SOFT};
    color: #ffffff;
}}

/* ── Scrollbars ──────────────────────────────────────────────────── */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    width: 8px;
    height: 8px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {INK_5};
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {INK_3};
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
    border: none;
    height: 0;
    width: 0;
}}
"""


def _install_font() -> str | None:
    """Register OPPO Sans with Qt's font DB and return the family name."""
    if not _FONT_PATH.is_file():
        return None
    font_id = QFontDatabase.addApplicationFont(str(_FONT_PATH))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else None


def _patch_navigation_selected_style() -> None:
    """Repaint NavigationPushButton's selected state as a black pill with
    white icon + white text (matches the CMS design). The library renders
    its background via QPainter, so QSS alone can't override it.
    """
    from PyQt6.QtCore import QRect, QRectF, QPoint, Qt
    from PyQt6.QtGui import QPainter, QColor, QCursor
    from qfluentwidgets.components.navigation.navigation_widget import (
        NavigationPushButton,
    )
    from qfluentwidgets.common.icon import drawIcon

    if getattr(NavigationPushButton, "_csm_patched", False):
        return

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setPen(Qt.PenStyle.NoPen)
        if self.isPressed:
            painter.setOpacity(0.7)
        if not self.isEnabled():
            painter.setOpacity(0.4)

        m = self._margins()
        pl, pr = m.left(), m.right()
        rect = self.rect()
        is_selected = self._canDrawIndicator()
        # Hover or about-to-be-selected hint (white-mode subtle bg).
        globalRect = QRect(self.mapToGlobal(QPoint()), self.size())
        is_hover = ((self.isEnter and globalRect.contains(QCursor.pos()))
                    or self.isAboutSelected) and self.isEnabled()

        ink = QColor(INK)
        if is_selected:
            painter.setBrush(ink)
            painter.drawRoundedRect(rect, 8, 8)
            fg = QColor("#ffffff")
        else:
            if is_hover:
                painter.setBrush(QColor(0, 0, 0, 10 if self.isAboutSelected else 16))
                painter.drawRoundedRect(rect, 8, 8)
            fg = self.textColor()

        # Icon
        icon_rect = QRectF(11.5 + pl, (self.height() - 16) / 2, 16, 16)
        if is_selected:
            from PyQt6.QtGui import QPixmap, QPainter as _QP
            icon = self._icon
            try:
                pm = QPixmap(16, 16)
                pm.fill(Qt.GlobalColor.transparent)
                ip = _QP(pm)
                drawIcon(icon, ip, QRectF(0, 0, 16, 16))
                ip.setCompositionMode(_QP.CompositionMode.CompositionMode_SourceIn)
                ip.fillRect(pm.rect(), QColor("#ffffff"))
                ip.end()
                painter.drawPixmap(icon_rect.toRect(), pm)
            except Exception:
                drawIcon(icon, painter, icon_rect)
        else:
            drawIcon(self._icon, painter, icon_rect)

        if self.isCompacted:
            return
        painter.setFont(self.font())
        painter.setPen(fg)
        left = 44 + pl if not self.icon().isNull() else pl + 16
        painter.drawText(
            QRectF(left, 0, self.width() - 13 - left - pr, self.height()),
            Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )

    NavigationPushButton.paintEvent = paintEvent
    NavigationPushButton._csm_patched = True


def apply_theme() -> None:
    setTheme(Theme.LIGHT)
    setThemeColor(PRIMARY_INK_GREEN)
    _patch_navigation_selected_style()
    app = QApplication.instance()
    if app is not None:
        family = _install_font()
        families = [family] if family else []
        families.extend(_FALLBACK_FAMILIES)
        font = QFont()
        font.setFamilies(families)
        app.setFont(font)
        existing = app.styleSheet() or ""
        if _APP_QSS.strip() not in existing:
            app.setStyleSheet(existing + "\n" + _APP_QSS)
