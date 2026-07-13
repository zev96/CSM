"""Singleton MonitorLoop manager.

The lifespan handler imports this and calls :func:`start` / :func:`stop`
to wire the periodic dispatcher to the FastAPI app's life. Tests that
need the loop running can call ``start()`` themselves; tests that don't
get the default no-op state.
"""
from __future__ import annotations

import logging
from pathlib import Path

from csm_core.config import AppConfig, read_api_key
from csm_core.monitor import storage
from csm_core.monitor.drivers import browser_driver
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
from csm_core.monitor.platforms.zhihu_question import ADAPTER as ZHIHU_ADAPTER
from csm_core.monitor.rate_limit import configure_pacing, configure_concurrency
from csm_core.monitor.tikhub import build_api_adapters

from . import config_service
from .monitor_loop import MonitorLoop, recover_run_progress
from ..monitor_bus import monitor_bus

logger = logging.getLogger(__name__)

_loop: MonitorLoop | None = None


def _apply_runtime_settings(cfg: AppConfig) -> None:
    """Push runtime-mutable monitor settings into the live adapters.

    Called from start() (first boot) and reconfigure() (every PATCH that
    touches monitor.*). NEVER raises — invalid config logs & old values
    stay in place, so PATCH /api/config still returns 200 with whatever
    the user wrote, and we don't surprise them with stale runtime state
    after a partial failure.

    Each adapter gets its own try/except so a failure in one (e.g. the
    browser driver can't find chrome.exe at the new path) doesn't stop
    the others from picking up the new pacing / exclude-domain values.
    """
    mcfg = cfg.monitor
    try:
        browser_driver.configure(mcfg.browser_engine, mcfg.chrome_path or "")
    except Exception as e:
        logger.exception("browser_driver.configure failed: %s", e)
    try:
        ZHIHU_ADAPTER.apply_settings(
            engine=mcfg.browser_engine,
            rotation_enabled=mcfg.multi_account_rotation,
            tasks_per_account=mcfg.tasks_per_account,
            cooldown_seconds=mcfg.cookie_cooldown_minutes * 60,
        )
    except Exception as e:
        logger.exception("ZHIHU_ADAPTER.apply_settings failed: %s", e)
    try:
        bcfg = mcfg.baidu_keyword
        BAIDU_ADAPTER.apply_settings(
            headless_default=bcfg.headless_default,
            captcha_visible_timeout_s=bcfg.captcha_visible_timeout_s,
            serp_pacing_seconds=bcfg.serp_pacing_seconds,
            article_pacing_seconds=bcfg.article_pacing_seconds,
            baijiahao_pacing_seconds=bcfg.baijiahao_pacing_seconds,
            breaker_failures=bcfg.breaker_failures,
            breaker_cooldown_seconds=bcfg.breaker_cooldown_seconds,
            default_excluded_domains=bcfg.default_excluded_domains,
            article_fetch_rank_cap=bcfg.article_fetch_rank_cap,
        )
    except Exception as e:
        logger.exception("BAIDU_ADAPTER.apply_settings failed: %s", e)
    # 评论平台（bilibili/douyin/kuaishou_comment）没有 apply_settings —— 它们
    # 用全局 pacer/semaphore。这里把 MonitorConfig 的节流/并发推进去，
    # 让设置页的「请求间隔」「每平台并发」对评论平台真正生效（默认 5-15s /
    # 并发 2 保持不变，防软封）。
    for platform in ("bilibili_comment", "douyin_comment", "kuaishou_comment"):
        try:
            configure_pacing(platform, mcfg.request_delay_min, mcfg.request_delay_max)
        except Exception:
            logger.exception("comment platform pacing config failed: %s", platform)
        try:
            configure_concurrency(platform, mcfg.concurrency_per_platform)
        except Exception:
            logger.exception("comment platform concurrency config failed: %s", platform)


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
        # R2 崩溃恢复：上次进程崩溃残留的 run-progress 草稿 → 可续抓断点。放在 loop
        # 起跑之前（此刻不会有 run 在写草稿）。fail-soft：恢复失败绝不打断启动。
        try:
            n = recover_run_progress()
            if n:
                logger.warning("R2: 恢复了 %d 个上次中断的 baidu run 为可续抓断点", n)
        except Exception:
            logger.exception("R2 recover_run_progress failed (non-fatal)")

    cfg = config_service.load()
    _apply_runtime_settings(cfg)
    _loop = MonitorLoop(
        event_sink=monitor_bus.publish,
        alert_top_n=cfg.monitor.alert_top_n,
        cooldown_hours=cfg.monitor.alert_cooldown_hours,
        # tick_seconds left at default 60 — APScheduler handles drift.
        api_adapters=build_api_adapters(config_service.load, read_api_key),
        data_source_mode=cfg.monitor.data_source_mode,
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


def reconfigure(cfg: AppConfig | None = None) -> None:
    """Re-push monitor settings into adapters without restarting the loop.

    Called from PATCH /api/config when ``monitor.*`` fields change so the
    user doesn't need to restart sidecar after editing default exclude
    domains / pacing / breaker thresholds / etc.

    No-op if start() hasn't been called yet — lifespan order ensures
    start() runs before HTTP routes accept requests, but defensive.

    ``cfg=None`` re-reads the latest from config_service (the usual path).
    Passing an explicit cfg is for tests that want to skip the disk read.
    """
    if _loop is None:
        return
    cfg = cfg or config_service.load()
    _apply_runtime_settings(cfg)
    _loop.set_data_source_mode(cfg.monitor.data_source_mode)
    # 告警阈值也热更，否则改 alert_top_n / alert_cooldown_hours 要重启才生效。
    _loop.set_alert_config(
        alert_top_n=cfg.monitor.alert_top_n,
        cooldown_hours=cfg.monitor.alert_cooldown_hours,
    )


def get() -> MonitorLoop | None:
    return _loop


def storage_initialized() -> bool:
    return storage._db_path is not None  # noqa: SLF001


def _default_db_path() -> Path:
    return config_service.get_path().parent / "monitor.db"
