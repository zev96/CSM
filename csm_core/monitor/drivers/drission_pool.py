"""DrissionPage singleton — used as the browser fallback for adapters.

Why singleton: launching a Chromium subprocess takes 2–5 seconds on
Windows. If every fetch on a slow path spins up its own page, a wave of
risk-controlled requests would bring the host machine to its knees. By
keeping one ``ChromiumPage`` alive across calls and idling it down after
``IDLE_SHUTDOWN_SECONDS`` of inactivity, the pool absorbs spikes without
holding 200MB of RAM forever.

Why DrissionPage and not Selenium / Playwright:
- Selenium needs ChromeDriver version-matching (the original Case-6 was
  brittle exactly because of this).
- Playwright bundles its own Chromium (~150MB into onedir).
- DrissionPage reuses the user's local Chrome at runtime, so onedir
  size stays sane and cookie/profile import works naturally.

This module is intentionally tolerant of import failure — DrissionPage
is an optional dependency in some deploys (a user might run only the
comment platforms which need only curl_cffi). Callers should treat
``get_page()`` raising ``RuntimeError`` as "fallback unavailable".
"""
from __future__ import annotations
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IDLE_SHUTDOWN_SECONDS = 300.0  # 5 minutes


_lock = threading.Lock()
_page: Any = None  # DrissionPage.ChromiumPage when initialized
_last_used: float = 0.0
_chrome_path: str = ""
_idle_thread: threading.Thread | None = None
_stop_event = threading.Event()


def configure(chrome_path: str = "") -> None:
    """Set the Chrome executable path. Empty string = auto-detect."""
    global _chrome_path
    _chrome_path = chrome_path.strip()


def get_page() -> Any:
    """Return the live ChromiumPage, launching it lazily if needed.

    Raises RuntimeError if DrissionPage isn't installed or Chrome can't
    be launched. The caller is expected to fall back to "report failed"
    in that case rather than try to keep going.
    """
    global _page, _last_used, _idle_thread
    with _lock:
        _last_used = time.monotonic()
        if _page is not None:
            return _page
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except ImportError as e:
            raise RuntimeError(
                "DrissionPage is not installed; browser fallback unavailable"
            ) from e
        opts = ChromiumOptions()
        # Prefer headless to keep the desktop quiet, but if the user has
        # configured a non-default Chrome path we honor it.
        if _chrome_path:
            opts.set_browser_path(_chrome_path)
        opts.set_argument("--headless=new")
        opts.set_argument("--disable-blink-features=AutomationControlled")
        opts.set_argument("--no-sandbox")
        opts.set_argument("--disable-dev-shm-usage")
        opts.set_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            _page = ChromiumPage(opts)
        except Exception as e:
            raise RuntimeError(f"failed to launch Chromium: {e}") from e
        # Spin up the idle reaper on first launch.
        if _idle_thread is None or not _idle_thread.is_alive():
            _stop_event.clear()
            _idle_thread = threading.Thread(
                target=_idle_reaper, name="drission-idle-reaper", daemon=True
            )
            _idle_thread.start()
        logger.info("DrissionPage Chromium launched (headless)")
        return _page


def shutdown() -> None:
    """Tear down the live page, if any. Safe to call repeatedly.

    Used at app exit and from the idle reaper. After shutdown the next
    ``get_page()`` will pay the launch cost again — that's intentional.
    """
    global _page, _idle_thread
    with _lock:
        if _page is not None:
            try:
                _page.quit()
            except Exception as e:
                logger.warning("DrissionPage shutdown raised: %s", e)
            _page = None
        _stop_event.set()


def set_cookies_for_domain(domain: str, cookies_text: str) -> None:
    """Apply a `key=value; key=value` cookie string to ``domain``."""
    page = get_page()
    cookies: list[dict[str, str]] = []
    for piece in cookies_text.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        k, _, v = piece.partition("=")
        cookies.append({"name": k.strip(), "value": v.strip(), "domain": domain})
    try:
        page.set.cookies(cookies)
    except Exception as e:
        logger.warning("failed to set cookies on %s: %s", domain, e)


def _idle_reaper() -> None:
    """Background thread that quits Chromium after a quiet period."""
    while not _stop_event.is_set():
        # Polling at 30s granularity is fine — 5min idle is the target,
        # ±30s slop is invisible.
        if _stop_event.wait(timeout=30.0):
            return
        with _lock:
            if _page is None:
                continue
            if time.monotonic() - _last_used >= IDLE_SHUTDOWN_SECONDS:
                logger.info(
                    "DrissionPage idle for %.0fs — shutting down to free RAM",
                    IDLE_SHUTDOWN_SECONDS,
                )
                try:
                    _page.quit()
                except Exception as e:
                    logger.warning("DrissionPage idle shutdown raised: %s", e)
                # Fall-through: clear state and let the loop exit; the
                # next get_page() will start a new reaper thread.
                _set_page_none()
                return


def _set_page_none() -> None:
    """Helper used by the reaper that already holds _lock."""
    global _page
    _page = None
