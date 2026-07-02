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
    reap_task: asyncio.Task | None = None
    if not _is_test_run():
        # Migrate pre-v0.4.5 Windows data dir BEFORE anything else opens
        # a file inside config_dir — once monitor_lifecycle / vault scan /
        # ensure_default_dirs start writing, copytree would race with
        # those writes.
        try:
            from csm_core.config import migrate_legacy_config_dir
            migrate_legacy_config_dir()
        except Exception:
            logger.exception("legacy data dir migration failed; continuing")
        # Drain any plaintext api_keys from settings.json into the OS
        # keyring. Cheap when empty; on a fresh upgrade pulls plaintext
        # out of disk before any route reads them.
        try:
            from csm_core.config import migrate_api_keys_to_keyring
            migrate_api_keys_to_keyring()
        except Exception:
            logger.exception("api_keys keyring migration failed; continuing")
        try:
            from .services import startup_dirs
            startup_dirs.ensure_default_dirs()
        except Exception:
            logger.exception("ensure_default_dirs failed; continuing")
        # Fire-and-forget background vault scan. Hold a reference locally so
        # the task isn't GC'd while pending (asyncio docs warn about this);
        # cancel it in finally so a slow scan doesn't leak past shutdown.
        auto_scan_task = asyncio.create_task(_auto_scan_vault())
        # Drop EventBus buffers whose SSE client never connected. Without
        # this, every job_id (generate/batch/dedup/updater) whose stream
        # was opened then closed without reading to `done` would leak its
        # queue + buffered events for the lifetime of the sidecar.
        reap_task = asyncio.create_task(_periodic_reap_stale())
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
            from .services import mining_service
            mining_service.init()
            from csm_core.browser_infra import mining_browser as _mb
            from csm_core import config as core_config
            # 登录态/浏览器 profile 统一放在 .auth/ 子目录下（含 cookie，不进 VCS）。
            # FEASIBILITY_ANALYSIS.md §2 阶段 1。
            _mb.configure_profile_root(
                core_config.default_config_dir() / ".auth" / "browser_profiles"
            )
        except Exception:
            logger.exception("mining_service init failed; continuing without mining")
        # Wire native-mode SSE events: BaiduKeywordAdapter → monitor_bus.
        # Injected here so csm_core never imports csm_sidecar directly.
        try:
            from csm_core.monitor.platforms import baidu_keyword as _bk_module
            from csm_sidecar.monitor_bus import monitor_bus as _monitor_bus
            from csm_sidecar.services.monitor_loop import MonitorEvent as _MonitorEvent
            from datetime import datetime as _datetime
            from typing import Any as _Any

            def _publish_native_event(payload: dict[str, _Any]) -> None:
                """从 csm_core 收到 dict 形态事件 → 包成 MonitorEvent → publish 到 monitor_bus。"""
                evt = _MonitorEvent(
                    kind=payload["kind"],
                    task_id=payload.get("task_id", 0),
                    at=_datetime.utcnow(),
                    remaining_s=payload.get("remaining_s"),
                    keyword=payload.get("keyword"),
                    kw_idx=payload.get("kw_idx"),
                )
                _monitor_bus.publish(evt)

            _bk_module.ADAPTER.set_event_publisher(_publish_native_event)

            # Notify hook：chrome_preflight / baidu_keyword 的 _notify() 默认 fallback
            # 到 logger.warning("notifier not configured")，会刷一堆没意义的 warning。
            # 实际系统通知由前端 SSE handler (monitorStatus.ts) 收到 native event
            # 后调 useSystemNotify 弹 ── 后端只发 SSE 事件就够了。
            # 这里注入 log-only notifier 是 reserved hook（万一以后想加后端 ── tray
            # icon、Slack webhook ── 在这里换个 impl 就行），同时消除 warning spam。
            from csm_core.monitor.drivers import chrome_preflight as _chrome_preflight

            def _log_only_notify(*, title: str, body: str) -> None:
                logger.info("baidu native notify: %s — %s", title, body)

            _chrome_preflight.set_notifier(_log_only_notify)
            _bk_module.set_notifier(_log_only_notify)
        except Exception:
            logger.exception("native event publisher injection failed; continuing without native SSE events")
    try:
        yield
    finally:
        if reap_task is not None and not reap_task.done():
            reap_task.cancel()
            try:
                await asyncio.wait_for(reap_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                logger.exception("reap_stale task raised during shutdown; ignoring")
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
        try:
            from .services import mining_service
            mining_service.shutdown()
        except Exception:
            logger.exception("mining_service shutdown raised; ignoring")
        # Drain the four service-owned ThreadPoolExecutors. Each service
        # exposes an idempotent ``shutdown()`` that cancels queued work
        # and nulls its module-level executor; the next ``submit()`` call
        # lazy-recreates the pool. This means we can safely run shutdown
        # under pytest's repeated TestClient lifecycle without poisoning
        # subsequent tests — which is exactly what blocked the first
        # attempt at this fix back in #38.
        for mod_name in ("generate_service", "batch_service", "dedup_service", "updater_service"):
            try:
                mod = __import__(
                    f"csm_sidecar.services.{mod_name}",
                    fromlist=["shutdown"],
                )
                mod.shutdown()
            except Exception:
                logger.exception("%s shutdown raised; ignoring", mod_name)


async def _periodic_reap_stale(interval_s: float = 60.0) -> None:
    """Tick ``event_bus.bus.reap_stale()`` on a background interval.

    The bus stores per-job queues for fire-and-forget worker output. A
    queue that nobody ever streams to ``done`` would otherwise stick around
    for the full sidecar lifetime — over a day this leaks memory in
    proportion to UI tab churn.
    """
    from .event_bus import bus
    while True:
        try:
            await asyncio.sleep(interval_s)
            reaped = bus.reap_stale()
            if reaped:
                logger.debug("EventBus reap_stale: %d buffers", reaped)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("reap_stale tick failed; continuing")


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
        await run_in_threadpool(vault_service.get, root)
        logger.info("auto vault scan completed: %s", root)
    except Exception as e:
        logger.warning("auto vault scan failed: %s", e)
