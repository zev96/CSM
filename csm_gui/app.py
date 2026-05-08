"""Create a configured QApplication and return it plus the main window."""
from __future__ import annotations
import logging
import shutil
import sys
from pathlib import Path
from PyQt6.QtCore import QCoreApplication, QStandardPaths
from PyQt6.QtWidgets import QApplication
from .theme import apply_theme
from .main_window import MainWindow
from .tray.single_instance import SingleInstance

logger = logging.getLogger(__name__)

# Stable identity for QStandardPaths so the config file lives at exactly
# one path regardless of how the user launched us (compiled CSM.exe vs.
# ``python -m csm_gui`` vs. ``python main.py`` — Qt would otherwise derive
# applicationName from sys.argv[0]'s basename and silently shard saves
# across "CSM/", "python/", and "main/" subtrees of %LOCALAPPDATA%).
#
# Note: we deliberately do NOT set organizationName. With orgName + appName
# both = "CSM", AppConfigLocation expands to ".../CSM/CSM", and after the
# extra "/CSM" we append in :func:`_default_config_dir` we'd land at
# ".../CSM/CSM/CSM". Leaving orgName empty keeps the path shape that all
# existing CSM.exe installs already use (".../CSM/CSM/settings.json").
APP_NAME = "CSM"

# Legacy paths we may need to migrate from. When users first ran with
# different launchers Qt wrote settings to whichever basename it inferred;
# we want to recover that prior config rather than greet returning users
# with a blank slate.
_LEGACY_APP_NAMES = ("python", "main", "py", "csm")


def _default_config_dir() -> Path:
    """Return ``<AppConfigLocation>/CSM``, ensuring it exists.

    Must be called *after* :func:`_set_app_identity` so ``AppConfigLocation``
    resolves with the stable ``APP_NAME`` instead of a sys.argv[0] basename.
    """
    loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    d = Path(loc) / "CSM" if loc else Path.home() / ".csm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_app_identity() -> None:
    """Pin organisation + application name so config paths are stable.

    Has to run before the QApplication's first call into QStandardPaths;
    we set it on the QCoreApplication-level singleton so it sticks even
    when an existing instance was constructed elsewhere (tests reuse the
    instance).
    """
    QCoreApplication.setApplicationName(APP_NAME)


def _is_essentially_empty_settings(path: Path) -> bool:
    """True if ``path`` is a settings.json that's never been configured.

    A first launch of CSM.exe writes a settings.json full of defaults the
    moment the user opens (and minimises) the app — even before they
    configure anything. For migration purposes such a file is "not real
    user data" and we'd rather honour a richer legacy file than block on
    the placeholder.
    """
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return (
        not data.get("api_keys")
        and not data.get("vault_root")
        and not data.get("out_dir")
        and data.get("default_provider", "mock") == "mock"
    )


def _migrate_legacy_settings(target_dir: Path) -> None:
    """One-shot migration of settings.json from a legacy launcher path.

    Skips when the target already holds real user configuration. If the
    target is missing OR is just a fresh-default placeholder (see
    :func:`_is_essentially_empty_settings`), we look at every known
    legacy basename under ``%LOCALAPPDATA%`` and copy the freshest
    *real* match into the new location, so users who first configured
    CSM via ``python -m csm_gui`` (which Qt mapped to ``.../python/CSM/``)
    don't lose their api_keys / default_provider on the upgrade.
    """
    target = target_dir / "settings.json"
    if target.exists() and not _is_essentially_empty_settings(target):
        return
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericConfigLocation
    ))
    if not base or not base.exists():
        return
    candidates: list[Path] = []
    for legacy in _LEGACY_APP_NAMES:
        legacy_file = base / legacy / "CSM" / "settings.json"
        if (
            legacy_file.exists()
            and legacy_file.resolve() != target.resolve()
            and not _is_essentially_empty_settings(legacy_file)
        ):
            candidates.append(legacy_file)
    if not candidates:
        return
    # Pick the most recently modified — that's the one the user was
    # actually using before this upgrade.
    src = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        # Back up the placeholder if present, then drop in the legacy file.
        if target.exists():
            target.rename(target.with_suffix(".json.bak"))
        shutil.copy2(src, target)
        logger.info("migrated settings from legacy path: %s -> %s", src, target)
    except OSError as e:
        logger.warning("failed to migrate legacy settings %s: %s", src, e)


def run() -> int:
    # Identity must be pinned before QApplication touches QStandardPaths.
    _set_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    # If something else already constructed the app (tests, embedding) and
    # left the names empty, re-apply.
    _set_app_identity()
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

    config_dir = _default_config_dir()
    _migrate_legacy_settings(config_dir)
    logger.info("CSM config dir: %s", config_dir)
    win = MainWindow(config_dir=config_dir)
    # Route the singleton's "show" message to the window's restore method.
    # Connect ONLY if instance is bound (otherwise show_requested never fires).
    if instance._acquired:
        instance.show_requested.connect(win._show_main_window)

    win.show()
    return app.exec()
