"""TrayManager wires the QSystemTrayIcon + TrayMenu and re-exposes signals."""
import pytest
from PyQt6.QtWidgets import QSystemTrayIcon
from csm_gui.tray.manager import TrayManager


def _skip_if_no_tray():
    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("system tray not available in this environment")


def test_manager_creates_when_tray_available(qtbot):
    _skip_if_no_tray()
    mgr = TrayManager()
    assert mgr.is_available() is True
    assert mgr.tray_icon is not None


def test_manager_tooltip(qtbot):
    _skip_if_no_tray()
    mgr = TrayManager()
    assert mgr.tray_icon.toolTip() == "CSM — Content Studio"


def test_manager_double_click_emits_show(qtbot):
    """Double-click on the tray icon should emit show_requested."""
    _skip_if_no_tray()
    mgr = TrayManager()
    with qtbot.waitSignal(mgr.show_requested, timeout=1000):
        mgr._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)


def test_manager_left_click_emits_show(qtbot):
    _skip_if_no_tray()
    mgr = TrayManager()
    with qtbot.waitSignal(mgr.show_requested, timeout=1000):
        mgr._on_activated(QSystemTrayIcon.ActivationReason.Trigger)


def test_manager_right_click_does_not_emit_show(qtbot):
    """Right-click shows the context menu, not the main window."""
    _skip_if_no_tray()
    mgr = TrayManager()
    received = []
    mgr.show_requested.connect(lambda: received.append(True))
    mgr._on_activated(QSystemTrayIcon.ActivationReason.Context)
    qtbot.wait(100)
    assert received == []


def test_manager_relays_menu_signals(qtbot):
    _skip_if_no_tray()
    mgr = TrayManager()
    with qtbot.waitSignal(mgr.new_article_requested, timeout=1000):
        mgr._menu.new_article_requested.emit()


def test_show_message_first_minimize(qtbot):
    """show_first_minimize_bubble triggers a tray notification."""
    _skip_if_no_tray()
    mgr = TrayManager()
    # Should not raise. Visually verifying the bubble is out of scope here.
    mgr.show_first_minimize_bubble()
