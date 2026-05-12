"""Singleton MonitorLoop manager.

The lifespan handler imports this and calls :func:`start` / :func:`stop`
to wire the periodic dispatcher to the FastAPI app's life. Tests that
need the loop running can call ``start()`` themselves; tests that don't
get the default no-op state.
"""
from __future__ import annotations

import logging
from pathlib import Path

from csm_core.monitor import storage

from . import config_service
from .monitor_loop import MonitorLoop
from ..monitor_bus import monitor_bus

logger = logging.getLogger(__name__)

_loop: MonitorLoop | None = None


def start(*, db_path: Path | None = None) -> MonitorLoop:
    """Idempotently start the loop. Initialises monitor.db on first call.

    ``db_path`` defaults to ``<config_dir>/monitor.db`` matching the
    legacy GUI shell. Passing an explicit path is for tests that want to
    co-locate the DB with their tmp settings.
    """
    global _loop
    if _loop is not None and _loop.is_running():
        return _loop

    if not storage_initialized():
        target = Path(db_path) if db_path else _default_db_path()
        storage.init_db(target)
        logger.info("monitor storage initialised at %s", target)

    cfg = config_service.load()
    mcfg = cfg.monitor
    _loop = MonitorLoop(
        event_sink=monitor_bus.publish,
        alert_top_n=mcfg.alert_top_n,
        cooldown_hours=mcfg.alert_cooldown_hours,
        # tick_seconds left at default 60 — APScheduler handles drift.
    )
    _loop.start()
    return _loop


def stop() -> None:
    global _loop
    if _loop is None:
        return
    try:
        _loop.stop(wait=True)
    finally:
        _loop = None


def get() -> MonitorLoop | None:
    return _loop


def storage_initialized() -> bool:
    return storage._db_path is not None  # noqa: SLF001


def _default_db_path() -> Path:
    return config_service.get_path().parent / "monitor.db"
