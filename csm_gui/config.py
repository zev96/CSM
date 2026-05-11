"""Backward-compat shim — real config now lives in :mod:`csm_core.config`.

The PyQt6 GUI is being replaced by a Tauri + Vue 3 frontend talking to a
Python sidecar that owns ``AppConfig``. To avoid touching dozens of GUI
callers during the transition, this module simply re-exports everything from
the new location. **Do not add new symbols here** — put them in
``csm_core/config.py``.

Once ``csm_gui/`` is removed (migration plan stage D), this file goes too.
"""
from __future__ import annotations

from csm_core.config import (  # noqa: F401  (re-export)
    AppConfig,
    CloseAction,
    MonitorConfig,
    Provider,
    default_config_dir,
    default_config_path,
    delete_secret,
    get_secret,
    load_config,
    save_config,
    set_secret,
)

__all__ = [
    "AppConfig",
    "CloseAction",
    "MonitorConfig",
    "Provider",
    "default_config_dir",
    "default_config_path",
    "delete_secret",
    "get_secret",
    "load_config",
    "save_config",
    "set_secret",
]
