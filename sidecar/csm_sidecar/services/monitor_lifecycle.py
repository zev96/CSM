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
from csm_core.monitor.drivers import browser_driver
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
from csm_core.monitor.platforms.zhihu_question import ADAPTER as ZHIHU_ADAPTER

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
    # 配置两个浏览器池 —— Patchright（默认）+ DrissionPage（兜底）。
    # browser_driver.configure 内部对两边都调 configure()，用户在 UI 切
    # 引擎不需要重启 sidecar。
    browser_driver.configure(mcfg.browser_engine, mcfg.chrome_path or "")
    # 推设置给 zhihu adapter —— 引擎选择 + 多账号轮换参数。
    # adapter 是 module-level singleton，apply_settings 重建 CookieStore 但
    # 不动 DB 行，所以多次调用安全。
    ZHIHU_ADAPTER.apply_settings(
        engine=mcfg.browser_engine,
        rotation_enabled=mcfg.multi_account_rotation,
        tasks_per_account=mcfg.tasks_per_account,
        cooldown_seconds=mcfg.cookie_cooldown_minutes * 60,
    )
    bcfg = mcfg.baidu_keyword
    BAIDU_ADAPTER.apply_settings(
        headless_default=bcfg.headless_default,
        captcha_visible_timeout_s=bcfg.captcha_visible_timeout_s,
        captcha_max_promotions=bcfg.captcha_max_promotions,
        serp_pacing_seconds=bcfg.serp_pacing_seconds,
        breaker_failures=bcfg.breaker_failures,
        breaker_cooldown_seconds=bcfg.breaker_cooldown_seconds,
        # 默认黑名单：B2B / 电商域名（jd / 1688 / taobao …）。
        # 任务级 exclude_domains 跟它合并使用 —— 见 BaiduKeywordAdapter._build_exclude_set。
        default_excluded_domains=bcfg.default_excluded_domains,
    )
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
