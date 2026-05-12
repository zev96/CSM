"""Startup / shutdown helpers — port allocation, token mint, stdout handshake."""
from __future__ import annotations

import asyncio
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

    * Bootstrap default Templates/Skills/History directories on first run
      and seed the bundled samples.
    * Kick off a background vault scan so BlockEditor 属性下拉在用户登
      陆首屏前就准备好（fire-and-forget — 扫描失败/超时不阻塞 sidecar）。
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
    auto_scan_task: asyncio.Task | None = None
    if not _is_test_run():
        try:
            from .services import startup_dirs
            startup_dirs.ensure_default_dirs()
        except Exception:
            logger.exception("ensure_default_dirs failed; continuing")
        # Fire-and-forget background vault scan. Hold a reference locally so
        # the task isn't GC'd while pending (asyncio docs warn about this);
        # cancel it in finally so a slow scan doesn't leak past shutdown.
        auto_scan_task = asyncio.create_task(_auto_scan_vault())
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
        if auto_scan_task is not None and not auto_scan_task.done():
            auto_scan_task.cancel()
            try:
                await asyncio.wait_for(auto_scan_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                logger.exception("auto vault scan task raised during shutdown; ignoring")
        if started_monitor:
            try:
                from .services import monitor_lifecycle
                monitor_lifecycle.stop()
            except Exception:
                logger.exception("MonitorLoop shutdown raised; ignoring")


async def _auto_scan_vault() -> None:
    """Background vault scan on startup — fire-and-forget.

    Reads ``AppConfig.vault_root`` and walks the tree once so cold-start
    requests to ``/api/vault/attributes`` already see a cached index. The
    BlockEditor still has a 409 self-heal fallback so this task missing or
    crashing degrades gracefully.
    """
    try:
        from pathlib import Path
        from fastapi.concurrency import run_in_threadpool
        from .services import config_service, vault_service

        cfg = config_service.load()
        if not cfg.vault_root:
            return
        root = Path(cfg.vault_root)
        if not root.is_dir():
            return
        await run_in_threadpool(vault_service.scan, root)
        logger.info("auto vault scan completed: %s", root)
    except Exception as e:
        logger.warning("auto vault scan failed: %s", e)
