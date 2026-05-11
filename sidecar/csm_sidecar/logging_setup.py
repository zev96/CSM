"""File logging for the sidecar.

Production sidecars write to ``<config_dir>/logs/sidecar.log`` with daily
rotation, keeping the last 7 days. Console output goes to stderr for
``tauri dev`` to surface in its terminal.

The handshake JSON line on stdout is the *only* thing we ever write to
stdout — the Rust shell parses it line-by-line and would choke on log
spam. Loggers therefore default to stderr.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"

_initialised = False


def setup(*, log_dir: Path | None = None, level: int = logging.INFO) -> Path | None:
    """Configure the root logger. Idempotent — second call is a no-op.

    Returns the on-disk log file path (or None if file logging failed).
    """
    global _initialised
    if _initialised:
        return None
    _initialised = True

    root = logging.getLogger()
    root.setLevel(level)

    # 1. Stderr handler — visible in `tauri dev` console / terminal where
    #    the sidecar was launched directly. NEVER stdout (handshake line).
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(stderr)

    # 2. Rotating file handler under config_dir/logs/. We don't import
    #    config_service here — it might not be initialised yet on early
    #    boot — instead caller passes log_dir explicitly. If it's None
    #    we fall back to skipping file logging (still get stderr).
    if log_dir is None:
        return None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "sidecar.log"
        fh = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=7,
            encoding="utf-8",
            delay=True,  # don't open the file until first write
        )
        fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        root.addHandler(fh)
        return log_file
    except OSError:
        # Directory unwritable / disk full / etc — keep stderr but skip files.
        root.warning("file logging unavailable; stderr only")
        return None


def default_log_dir() -> Path:
    """Best-effort per-user log dir.

    Mirrors :func:`csm_core.config.default_config_dir`'s platform layout so
    settings.json and logs/ live side by side.
    """
    from csm_core.config import default_config_dir
    return default_config_dir() / "logs"
