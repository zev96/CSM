"""Startup / shutdown helpers — port allocation, token mint, stdout handshake."""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from . import auth

logger = logging.getLogger(__name__)


def _is_test_run() -> bool:
    """Pytest sets ``PYTEST_CURRENT_TEST`` for every test. We use it to skip
    the parts of startup that touch real disk / spawn schedulers — tests
    init those explicitly via fixtures when they need them."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CSM_SIDECAR_TESTING"))


def pick_free_port() -> int:
    """Ask the kernel for any available TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def emit_handshake(port: int, token: str) -> None:
    """Print the handshake JSON line that Tauri reads from sidecar stdout.

    Format is intentionally a single line so the Rust spawner can do a
    line-buffered read with no JSON-streaming parser. Anything the user
    might log later goes to stderr, never stdout.
    """
    payload = {"port": port, "token": token, "version": 1}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: token is minted before the app accepts requests.

    In production (non-pytest) we additionally:

    * Initialise the monitor sqlite db at ``<config_dir>/monitor.db``
    * Start the APScheduler-driven :class:`MonitorLoop`

    Under pytest these are skipped — fixtures opt in per test so failures
    in the monitor lifecycle don't bleed into unrelated tests."""
    # main.run() mints the token *before* uvicorn binds (so the handshake
    # can hit stdout in time). Only mint here when nothing called us yet —
    # i.e. tests / `uvicorn ... main:app` direct usage. Otherwise we'd
    # invalidate the token Tauri already captured.
    if auth._TOKEN is None:
        auth.generate_token()
    started_monitor = False
    if not _is_test_run():
        try:
            # Local import so test-only imports don't pull in apscheduler.
            from .services import monitor_lifecycle
            monitor_lifecycle.start()
            started_monitor = True
        except Exception:
            # Failure here shouldn't kill the whole sidecar — the user can
            # still generate articles, just not run scheduled monitoring.
            logger.exception("MonitorLoop failed to start; continuing without it")
    try:
        yield
    finally:
        if started_monitor:
            try:
                from .services import monitor_lifecycle
                monitor_lifecycle.stop()
            except Exception:
                logger.exception("MonitorLoop shutdown raised; ignoring")
