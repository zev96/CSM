"""Orphan self-shutdown — defensive resilience for the sidecar.

If the Tauri shell crashes or is killed without first calling
``POST /api/shutdown``, the sidecar would otherwise keep running and
hold the loopback port. Two complementary mechanisms guard against that:

1. **Parent-PID watchdog** (preferred) — snapshot ``os.getppid()`` at
   startup; a background thread polls every 30s and exits the sidecar
   the moment that PID disappears. This handles the orphan case
   exactly and doesn't false-positive on a quiet but live Tauri.

2. **Inactivity watchdog** (safety net) — tracks the last incoming
   request via middleware. Default timeout is 24h, so it effectively
   never fires in normal desktop usage; it's there for the rare case
   where the parent PID is recycled before we notice. Set
   ``CSM_SIDECAR_HEARTBEAT_TIMEOUT=0`` to disable entirely.

History note: the inactivity timeout used to be 600s (10 min). That's
fine for a daemon that bursts then idles, but for a Tauri desktop app
the user often leaves the window open while reading; 10 min of no API
calls is normal and the sidecar dying mid-session breaks every
subsequent click. Bumped to 24h after observing in production.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time

from fastapi import Request

logger = logging.getLogger(__name__)

# Inactivity timeout: 24h default — effectively a safety net only.
HEARTBEAT_TIMEOUT = float(os.environ.get("CSM_SIDECAR_HEARTBEAT_TIMEOUT", "86400"))
POLL_INTERVAL = 30.0

# Snapshot parent PID at module import (= sidecar startup). For Tauri
# this is the csm-tauri.exe process. If it disappears, we orphan-exit.
# Set CSM_SIDECAR_PARENT_WATCHDOG=0 to disable (e.g. when running the
# sidecar standalone for browser-only dev, where the shell parent isn't
# meaningful).
_PARENT_PID_AT_BOOT = os.getppid()
PARENT_WATCHDOG_ENABLED = (
    os.environ.get("CSM_SIDECAR_PARENT_WATCHDOG", "1") not in ("0", "false", "no")
)

_last_activity = time.monotonic()
_started = False


async def heartbeat_middleware(request: Request, call_next):
    """ASGI middleware: bump ``_last_activity`` on every request."""
    global _last_activity
    _last_activity = time.monotonic()
    return await call_next(request)


def _self_terminate(reason: str) -> None:
    logger.warning("sidecar self-terminating: %s", reason)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        os._exit(1)


def _parent_alive(pid: int) -> bool:
    """Cross-platform best-effort: True iff *pid* is a live process."""
    if pid <= 1:
        # PID 1 / 0 means we're already orphaned (init reparented us).
        return False
    try:
        if os.name == "nt":
            # Windows: OpenProcess via ctypes is heavier; use psutil if
            # available, otherwise fall back to assuming alive.
            import psutil  # type: ignore
            return psutil.pid_exists(pid)
        # POSIX: signal 0 = existence check, doesn't actually signal.
        os.kill(pid, 0)
        return True
    except ImportError:
        return True  # psutil missing on Windows — fail open
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but we can't signal — that's fine
    except Exception:
        return True


def start_watchdog() -> None:
    """Spawn the daemon threads. Idempotent."""
    global _started
    if _started:
        return
    _started = True

    if PARENT_WATCHDOG_ENABLED and _PARENT_PID_AT_BOOT > 1:
        logger.info(
            "parent watchdog: exit when PID %d (parent) disappears",
            _PARENT_PID_AT_BOOT,
        )

        def _parent_loop() -> None:
            while True:
                time.sleep(POLL_INTERVAL)
                if not _parent_alive(_PARENT_PID_AT_BOOT):
                    _self_terminate(f"parent PID {_PARENT_PID_AT_BOOT} gone")
                    return

        threading.Thread(
            target=_parent_loop, daemon=True, name="parent-watchdog"
        ).start()
    else:
        logger.info("parent watchdog disabled")

    if HEARTBEAT_TIMEOUT <= 0:
        logger.info("inactivity watchdog disabled (timeout=%s)", HEARTBEAT_TIMEOUT)
        return

    def _idle_loop() -> None:
        logger.info(
            "inactivity watchdog: %ds (~%dh) no requests → SIGTERM",
            int(HEARTBEAT_TIMEOUT),
            int(HEARTBEAT_TIMEOUT // 3600),
        )
        while True:
            time.sleep(POLL_INTERVAL)
            idle = time.monotonic() - _last_activity
            if idle > HEARTBEAT_TIMEOUT:
                _self_terminate(f"no activity for {int(idle)}s")
                return

    threading.Thread(
        target=_idle_loop, daemon=True, name="inactivity-watchdog"
    ).start()


def reset_for_test() -> None:
    """Test-only — reset module state so unit tests can re-init."""
    global _last_activity, _started
    _last_activity = time.monotonic()
    _started = False
