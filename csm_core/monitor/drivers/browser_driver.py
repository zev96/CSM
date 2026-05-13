"""Engine-agnostic browser interface used by the monitor adapters.

This module decouples adapters (``zhihu_question`` etc.) from the
concrete browser library so we can A/B between Patchright (default) and
DrissionPage (legacy fallback) without sprinkling ``if engine == ...``
throughout the scraping code.

Why a Protocol-style facade and not a class hierarchy:
    - The two pools have very different lifecycles (Drission keeps a
      page handle; Patchright keeps a browser-context-page triple).
      Subclassing would force one to pretend it's the other.
    - Adapters need very few primitives: navigate, read current url,
      inject cookies, run JS, count nodes, wait for a selector. Anything
      beyond that belongs *inside* the driver implementation.
    - Tests can swap in a fake by name without monkey-patching pools.

Capability slice: every method here must work the same on both engines
or the adapter code will diverge. CSS injection / scroll loops are done
via ``evaluate_js`` — both engines expose JS eval, so that's the cheapest
common denominator. We deliberately do *not* expose locator/element
objects — those APIs are wildly different and the adapter doesn't need
DOM walking (the bulk-extract JS pulls everything in one round trip).
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class BrowserDriver(Protocol):
    """The capability surface adapters use.

    A driver instance is single-use per fetch — the *pool* owns the
    long-lived browser process and hands out short-lived driver shells.
    That way an exception during scraping doesn't leak resources, and
    the pool can implement its own warm-restart logic.
    """

    def navigate(self, url: str) -> None: ...
    def current_url(self) -> str: ...
    def inject_cookies(self, domain: str, cookies_text: str) -> None: ...
    def clear_cookies(self, domain: str | None = None) -> None: ...
    def read_cookie_names(self, domain_substring: str = "") -> list[str]: ...
    def evaluate_js(self, js: str, *args: Any) -> Any: ...
    def query_count(self, css: str) -> int: ...
    def wait_for_any(self, css: str, timeout_s: float) -> bool: ...


def get_driver(engine: str) -> BrowserDriver:
    """Hand out a ready-to-use driver shell for ``engine``.

    ``engine`` is one of:
        - ``"patchright"`` (default) — uses the Patchright stealth fork
          of Playwright. First call may block on Chromium download.
        - ``"drission"`` — the older DrissionPage-backed path. Kept as a
          fallback for users whose machine can't run Patchright (e.g.
          Win7, no `patchright install chromium` access).

    Raises ``RuntimeError`` if the underlying pool can't produce a page
    — adapters should treat that as "browser fallback unavailable" and
    record a failure rather than retrying in a loop.
    """
    if engine == "drission":
        from . import drission_pool, drission_driver
        page = drission_pool.get_page()
        return drission_driver.DrissionDriver(page)
    # Default + explicit "patchright"
    from . import patchright_pool, patchright_driver
    page = patchright_pool.get_page()
    return patchright_driver.PatchrightDriver(page)


def configure(engine: str, chrome_path: str = "") -> None:
    """Configure the pool selected by ``engine``. Idempotent.

    Called from monitor_lifecycle on sidecar startup with the user's
    settings. We configure *both* pools defensively so a runtime switch
    in the UI doesn't require a sidecar restart — the unused pool simply
    sits idle.
    """
    # Configure each pool we might need. Failures in either configure()
    # are logged but not raised — the pool still starts lazily on first
    # get_page(), where the error surfaces with a useful message.
    try:
        from . import drission_pool
        drission_pool.configure(chrome_path)
    except Exception:
        logger.exception("drission_pool.configure failed (non-fatal)")
    try:
        from . import patchright_pool
        patchright_pool.configure(chrome_path)
    except Exception:
        logger.exception("patchright_pool.configure failed (non-fatal)")


def shutdown_all() -> None:
    """Tear down every pool. Called from the sidecar lifespan handler."""
    for mod in ("drission_pool", "patchright_pool"):
        try:
            m = __import__(f"csm_core.monitor.drivers.{mod}", fromlist=["shutdown"])
            m.shutdown()
        except Exception:
            logger.debug("shutdown of %s raised (non-fatal)", mod, exc_info=True)
