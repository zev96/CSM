"""Patchright-backed BrowserDriver shim.

Wraps a Playwright Page (sync API) and exposes the engine-agnostic
surface from ``browser_driver``. Symmetric with ``drission_driver`` so
adapters look identical regardless of engine.

JS arg convention: ``evaluate_js(js, *args)`` makes ``args`` available
inside the JS body as a real Array (not Playwright's named-parameter
pattern, not DrissionPage's ``arguments`` pseudo-array). Both engine
shims normalize to this convention so adapters write one JS snippet
that works on either.
"""
from __future__ import annotations

import logging
from typing import Any

from . import patchright_pool

logger = logging.getLogger(__name__)


class PatchrightDriver:
    """BrowserDriver implementation over Playwright's sync Page."""

    def __init__(self, page: Any) -> None:
        self._page = page

    def navigate(self, url: str) -> None:
        # ``wait_until="domcontentloaded"`` is enough: the adapter does
        # its own scroll/wait loop, and zhihu's networkidle never
        # actually settles (telemetry beacons keep firing).
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("PatchrightDriver.navigate(%s) raised: %s", url, e)

    def current_url(self) -> str:
        try:
            return self._page.url or ""
        except Exception:
            return ""

    def inject_cookies(self, domain: str, cookies_text: str) -> None:
        patchright_pool.set_cookies_for_domain(domain, cookies_text)

    def clear_cookies(self, domain: str | None = None) -> None:
        patchright_pool.clear_cookies_for_domain(domain or "")

    def read_cookie_names(self, domain_substring: str = "") -> list[str]:
        return patchright_pool.read_cookie_names(domain_substring)

    def evaluate_js(self, js: str, *args: Any) -> Any:
        """Run ``js`` in the page; ``args`` is bound to a JS Array named ``args``.

        Implementation: Playwright's ``evaluate`` takes ONE arg
        (serialised to JSON), passed as the first parameter to the JS
        function. We wrap the caller's snippet so it sees a top-level
        ``args`` reference, then add ``return`` at the end if the body
        already contains its own ``return`` — otherwise the JS body's
        own ``return`` propagates as the value.
        """
        wrapped = (
            "(__csmArgs) => {\n"
            "  const args = __csmArgs;\n"
            f"  {js}\n"
            "}"
        )
        try:
            return self._page.evaluate(wrapped, list(args))
        except Exception as e:
            logger.warning("PatchrightDriver.evaluate_js raised: %s", e)
            return None

    def query_count(self, css: str) -> int:
        try:
            # ``locator.count()`` returns a number without materializing
            # ElementHandles — safe to call in the scroll loop without
            # piling up handles that need disposal.
            return self._page.locator(css).count()
        except Exception:
            return 0

    def wait_for_any(self, css: str, timeout_s: float) -> bool:
        try:
            self._page.locator(css).first.wait_for(
                state="attached", timeout=int(timeout_s * 1000),
            )
            return True
        except Exception:
            return False
