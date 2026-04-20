"""Win11 Fluent theme with #0067C0 primary + white background.

NO emojis — all icons must use qfluentwidgets.FluentIcon enum values.
"""
from __future__ import annotations
from PyQt6.QtGui import QColor
from qfluentwidgets import setTheme, setThemeColor, Theme

PRIMARY_BLUE = QColor("#0067C0")


def apply_theme() -> None:
    setTheme(Theme.LIGHT)
    setThemeColor(PRIMARY_BLUE)
