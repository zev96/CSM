"""TrayManager: owns QSystemTrayIcon, hooks up menu, exposes uniform signals.

Lifetime: created in app.py and held by MainWindow. Single instance per
process. Calling ``show()`` is what makes the icon visible — no tray
appears until the manager is told to.
"""
from __future__ import annotations
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QSystemTrayIcon
from .icon import load_tray_icon
from .menu import TrayMenu

_TOOLTIP = "CSM — Content Studio"
_FIRST_MINIMIZE_TITLE = "CSM 已最小化到托盘"
_FIRST_MINIMIZE_MSG = (
    "CSM 在后台运行。可在右下角托盘图标双击恢复主界面，"
    "或在设置中改回直接退出。"
)


class TrayManager(QObject):
    """Combines QSystemTrayIcon + TrayMenu, re-exposes the menu's signals.

    Right-click shows the menu. Left/double click emits ``show_requested``.
    """

    show_requested = pyqtSignal()
    new_article_requested = pyqtSignal()
    new_template_requested = pyqtSignal()
    new_skill_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._available = QSystemTrayIcon.isSystemTrayAvailable()
        self._menu = TrayMenu()
        self.tray_icon: QSystemTrayIcon | None = None
        if self._available:
            self.tray_icon = QSystemTrayIcon(load_tray_icon(), self)
            self.tray_icon.setToolTip(_TOOLTIP)
            self.tray_icon.setContextMenu(self._menu)
            self.tray_icon.activated.connect(self._on_activated)
        self._wire_menu()

    def _wire_menu(self) -> None:
        self._menu.show_requested.connect(self.show_requested.emit)
        self._menu.new_article_requested.connect(self.new_article_requested.emit)
        self._menu.new_template_requested.connect(self.new_template_requested.emit)
        self._menu.new_skill_requested.connect(self.new_skill_requested.emit)
        self._menu.settings_requested.connect(self.settings_requested.emit)
        self._menu.quit_requested.connect(self.quit_requested.emit)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger == single left click (Win + Linux). DoubleClick == double left click.
        # Context == right click → Qt automatically shows the contextMenu.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def is_available(self) -> bool:
        return self._available

    def show(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.show()

    def hide(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.hide()

    def show_first_minimize_bubble(self) -> None:
        if self.tray_icon is None:
            return
        # 5000ms → 5s, the OS may shorten this on its own.
        self.tray_icon.showMessage(
            _FIRST_MINIMIZE_TITLE, _FIRST_MINIMIZE_MSG,
            QSystemTrayIcon.MessageIcon.Information, 5000,
        )
