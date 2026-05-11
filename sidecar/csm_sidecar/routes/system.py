"""System endpoints: health, version, shutdown.

These three are the only routes that *don't* require the bearer token —
``/health`` lets Tauri verify the sidecar is up before it knows the token,
and ``/version`` is read by the auto-updater.
"""
from __future__ import annotations

import os
import signal

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
    """Cooperative shutdown — Tauri calls this when the window closes."""
    # Schedule the kill on the next event-loop tick so the response can
    # actually be returned to the client first.
    import asyncio

    loop = asyncio.get_running_loop()
    loop.call_later(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"status": "shutting down"}
