"""Startup directory bootstrap — runs once at sidecar startup.

Responsibilities:
1. Make sure ``default_template / skill_dir / dedup_history_dir`` point to
   real, writable folders. Empty fields are filled with per-user defaults
   under ``%LOCALAPPDATA%\\CSM\\CSM\\`` (see csm_core.config).
2. Seed brand-new Templates/Skills folders with the bundled samples so a
   fresh install has something to choose from. Skipped if the target dir
   already has content (won't clobber user-made templates).

Idempotent — safe to call repeatedly. Failures are logged but never raise:
the sidecar should still come up even if disk I/O is wonky.
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

from csm_core import config as core_config

from . import config_service

logger = logging.getLogger(__name__)


# Indirection makes the two paths individually monkeypatch-able in tests
# without polluting csm_core or fiddling with sys._MEIPASS.
def _default_config_dir() -> Path:
    return core_config.default_config_dir()


def _resource_dir() -> Path:
    """Locate the bundled ``templates/`` and ``examples/`` resource roots.

    In a PyInstaller --onefile bundle these are extracted under
    ``sys._MEIPASS``. In dev (``python -m csm_sidecar.main``) they live at
    the repo root, two levels up from this file.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    # csm_sidecar/services/startup_dirs.py -> sidecar/csm_sidecar/services -> sidecar -> repo
    return Path(__file__).resolve().parents[3]


def ensure_default_dirs() -> None:
    """Bootstrap user-data directories. Safe to call on every startup."""
    cfg = config_service.load()
    base = _default_config_dir()
    resource = _resource_dir()

    patches: dict[str, str] = {}

    plan = [
        ("default_template", base / "Templates", resource / "templates"),
        ("skill_dir",        base / "Skills",    resource / "examples" / "skills"),
        ("dedup_history_dir",base / "History",   None),
    ]

    for field, default_target, seed_source in plan:
        current = (getattr(cfg, field, None) or "").strip()
        target = Path(current) if current else default_target
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("ensure_default_dirs: mkdir %s failed: %s", target, e)
            continue
        if not current:
            patches[field] = str(target)
            if seed_source is not None:
                _seed_dir(seed_source, target)

    if patches:
        try:
            config_service.patch(patches)
        except Exception as e:
            logger.warning("ensure_default_dirs: persist patches failed: %s", e)


def _seed_dir(src: Path, dst: Path) -> None:
    """Copy every regular file from ``src`` into ``dst`` once.

    No-op when ``dst`` is already non-empty (user might have hand-curated
    templates we don't want to mix bundled samples into). Top-level files
    only — bundled templates/skills are flat.
    """
    if not src.is_dir():
        return
    try:
        if any(dst.iterdir()):
            return
    except OSError:
        return
    for f in src.iterdir():
        if not f.is_file():
            continue
        try:
            shutil.copy2(f, dst / f.name)
        except OSError as e:
            logger.warning("_seed_dir: copy %s -> %s failed: %s", f, dst, e)
