"""Create a configured QApplication and return it plus the main window."""
from __future__ import annotations
import sys
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from .theme import apply_theme
from .main_window import MainWindow

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _default_config_dir() -> Path:
    loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    d = Path(loc) / "CSM" if loc else Path.home() / ".csm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    icon_path = _ASSETS_DIR / "csm.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    apply_theme()
    win = MainWindow(config_dir=_default_config_dir())
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    return app.exec()
