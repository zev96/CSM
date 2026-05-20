"""System endpoints: health, version, shutdown.

These three are the only routes that *don't* require the bearer token —
``/health`` lets Tauri verify the sidecar is up before it knows the token,
and ``/version`` is read by the auto-updater.
"""
from __future__ import annotations

import signal
import threading

from fastapi import APIRouter

from .. import __version__
from ..auth import RequireToken

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/version")
async def version() -> dict[str, str]:
    return {"sidecar": __version__}


@router.post("/api/shutdown", dependencies=[RequireToken])
async def shutdown() -> dict[str, str]:
    """Cooperative shutdown — Tauri calls this when the window closes.

    We raise SIGINT (not SIGTERM via ``os.kill``) so uvicorn's registered
    signal handler runs ``Server.handle_exit`` → drains in-flight requests
    → calls the lifespan ``finally`` block. The old SIGTERM path on
    Windows mapped to ``TerminateProcess`` (immediate hard kill), which
    bypassed the lifespan and left half-downloaded updater binaries in
    %CONFIG%/updates/ — see C4 in the v0.5.2 stability audit.

    Delivered from a worker thread after a short delay so this handler
    can return 200 first.
    """
    def _raise_sigint_soon() -> None:
        import time
        time.sleep(0.1)
        # signal.raise_signal routes through Python's registered handler,
        # which is what uvicorn installed. Works the same on POSIX and
        # Windows (unlike os.kill which on Windows is TerminateProcess).
        signal.raise_signal(signal.SIGINT)

    threading.Thread(target=_raise_sigint_soon, daemon=True).start()
    return {"status": "shutting down"}
