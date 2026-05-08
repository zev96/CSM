"""Create a configured QApplication and return it plus the main window."""
from __future__ import annotations
import logging
import sys
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication
from .theme import apply_theme
from .main_window import MainWindow
from .tray.single_instance import SingleInstance

logger = logging.getLogger(__name__)


def _default_config_dir() -> Path:
    loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    d = Path(loc) / "CSM" if loc else Path.home() / ".csm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # Critical: prevent Qt from quitting when MainWindow is hidden to tray.
    # Without this, hide() == quit() because no other top-level windows exist.
    app.setQuitOnLastWindowClosed(False)

    apply_theme()

    # Single-instance lock. If another CSM is already running, ask it to show
    # itself and exit cleanly here.
    instance = SingleInstance("csm-app-singleton")
    if not instance.try_acquire():
        # try_acquire returned False — could be either:
        #   (a) another instance is running and answering on the pipe
        #   (b) listen() failed for non-stale reasons (permissions / resource)
        # send_show distinguishes: True == server answered, False == nobody home
        if instance.send_show():
            return 0
        # Bind failure with no other instance — log and continue WITHOUT the
        # single-instance guarantee rather than silently exiting. The user gets
        # CSM. The cost is rare data race if a second copy starts later.
        logger.warning(
            "SingleInstance.try_acquire() failed but no other instance answered. "
            "Continuing without single-instance lock."
        )

    win = MainWindow(config_dir=_default_config_dir())
    # Route the singleton's "show" message to the window's restore method.
    # Connect ONLY if instance is bound (otherwise show_requested never fires).
    if instance._acquired:
        instance.show_requested.connect(win._show_main_window)

    win.show()
    return app.exec()
