"""DrissionPage-backed BrowserDriver shim.

Wraps a live ``ChromiumPage`` from ``drission_pool.get_page()`` and
exposes the engine-agnostic surface defined in ``browser_driver``.

Kept thin on purpose: the heavy logic (lifecycle, idle reaper, Chrome
launch) lives in ``drission_pool``; this module just normalises the
method names so adapters can call ``driver.navigate(url)`` regardless
of which engine answered.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from . import drission_pool

logger = logging.getLogger(__name__)


class DrissionDriver:
    """BrowserDriver implementation over DrissionPage's ChromiumPage."""

    def __init__(self, page: Any) -> None:
        self._page = page

    def navigate(self, url: str) -> None:
        self._page.get(url)

    def current_url(self) -> str:
        try:
            return self._page.url or ""
        except Exception:
            return ""

    def inject_cookies(self, domain: str, cookies_text: str) -> None:
        # Delegate to the pool helper — keeps domain-prefix handling in
        # one place across both engines.
        drission_pool.set_cookies_for_domain(domain, cookies_text)

    def clear_cookies(self, domain: str | None = None) -> None:
        """Clear cookies on the DrissionPage side.

        DrissionPage 4.x exposes ``page.set.cookies([])`` for "replace
        with empty list" rather than a dedicated clear API. We also try
        the dev-tools-style ``Network.clearBrowserCookies`` as a more
        thorough fallback — sometimes set.cookies([]) only clears the
        ones with matching attributes, which isn't what we want.
        """
        try:
            # Best-effort: replace whole jar.
            self._page.set.cookies([])
        except Exception:
            pass
        try:
            self._page.run_cdp("Network.clearBrowserCookies")
        except Exception:
            # Older DrissionPage doesn't expose run_cdp; the set.cookies([])
            # path above is good enough for most users.
            pass

    def read_cookie_names(self, domain_substring: str = "") -> list[str]:
        try:
            cookies = self._page.cookies(as_dict=False)  # list of dicts
        except Exception:
            return []
        if not domain_substring:
            return [c.get("name", "") for c in cookies]
        return [
            c.get("name", "") for c in cookies
            if domain_substring in (c.get("domain") or "")
        ]

    def evaluate_js(self, js: str, *args: Any) -> Any:
        """Run ``js`` with positional args exposed as a JS Array named ``args``.

        Convention shared with PatchrightDriver — adapters reference
        ``args[0]``, ``args[1]`` etc inside their JS. DrissionPage
        natively exposes positional args as ``arguments[i]``, so we
        prepend an alias line that lifts them onto our ``args`` name.
        Costs one DOM-less JS line; keeps adapter code engine-agnostic.
        """
        bridge = "var args = Array.prototype.slice.call(arguments);\n"
        try:
            return self._page.run_js(bridge + js, *args)
        except Exception as e:
            logger.warning("DrissionDriver.evaluate_js raised: %s", e)
            return None

    def query_count(self, css: str) -> int:
        # DrissionPage 4.x requires the explicit `css:` prefix — see
        # the long-form note in zhihu_question.py for the gory history.
        try:
            return len(self._page.eles(f"css:{css}"))
        except Exception:
            return 0

    def wait_for_any(self, css: str, timeout_s: float) -> bool:
        """Block up to ``timeout_s`` seconds for any element matching ``css``.

        We poll instead of using DrissionPage's wait helpers because those
        differ wildly between 3.x and 4.x — a simple poll loop is portable
        and the cost (0.3s sleep granularity) is negligible compared to
        the 5–15s lazy-mount wait we're already paying.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.query_count(css) > 0:
                return True
            time.sleep(0.3)
        return False
