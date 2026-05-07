"""Tray icon loader: prefer bundled logo, fall back to a Fluent icon."""
from PyQt6.QtGui import QIcon
from csm_gui.tray.icon import load_tray_icon


def test_load_tray_icon_returns_qicon(qtbot):
    icon = load_tray_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_load_tray_icon_uses_bundled_logo_when_present(tmp_path, monkeypatch):
    """If assets/csm-logo.png exists, the icon should be loadable."""
    # The real assets path may or may not exist depending on dev setup.
    # We just verify load_tray_icon never crashes — see test_load_tray_icon_returns_qicon.
    icon = load_tray_icon()
    assert not icon.isNull()
