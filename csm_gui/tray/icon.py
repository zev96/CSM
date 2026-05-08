"""Tray icon loader.

Prefers ``csm_gui/assets/csm-logo.png`` if shipped with the build;
falls back to qfluentwidgets' FluentIcon.HOME so the tray works even
before the asset is bundled.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtGui import QIcon


def load_tray_icon() -> QIcon:
    """Return a non-null QIcon suitable for QSystemTrayIcon.

    The icon should be at least 16×16; both ``.png`` and the FluentIcon
    fallback satisfy this.
    """
    logo = Path(__file__).resolve().parent.parent / "assets" / "csm-logo.png"
    if logo.exists():
        ic = QIcon(str(logo))
        if not ic.isNull():
            return ic

    # Fallback: qfluentwidgets ships icons as resource paths usable by QIcon.
    try:
        from qfluentwidgets import FluentIcon
        return FluentIcon.HOME.icon()
    except Exception:
        # Absolute last resort: the Qt standard icon. Still non-null.
        from PyQt6.QtWidgets import QApplication, QStyle
        app = QApplication.instance()
        if app is not None:
            return app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        return QIcon()
