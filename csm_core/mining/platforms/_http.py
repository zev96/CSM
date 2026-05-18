"""HTTP helpers for mining-platform adapters.

The Patchright Page is used to ESTABLISH login state (cookies land in the
BrowserContext). Then we extract those cookies and make signed API calls
via httpx — same pattern as MediaCrawler kuaishou/client.py:142-145 and
bilibili/client.py:169-176. Bypasses SPA bot fingerprinting that hits the
rendered search pages.
"""
from __future__ import annotations

from typing import Any

import httpx


_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)


def cookies_from_context(
    context: Any, urls: list[str]
) -> tuple[str, dict[str, str]]:
    """Extract cookies the browser would send when fetching ``urls``.

    Returns ``(cookie_header_string, cookies_dict)``. The string form is
    ``"k=v; k=v"`` suitable for ``headers["Cookie"]``; the dict is handy
    for ``httpx.Client(cookies=...)`` or direct membership checks.

    Patchright's ``context.cookies(urls)`` returns a list of dicts with
    name/value/domain/expires/secure/sameSite. We collapse duplicates by
    name, keeping the entry with the latest ``expires`` — Patchright may
    return multiple entries for the same cookie name when the cookie is
    set on overlapping domains (e.g. ``.kuaishou.com`` AND
    ``www.kuaishou.com`` after ``_inject_monitor_cookies`` over-injects).
    """
    raw = context.cookies(urls) or []
    by_name: dict[str, dict[str, Any]] = {}
    for c in raw:
        name = c.get("name", "")
        if not name:
            continue
        prev = by_name.get(name)
        if prev is None or c.get("expires", 0) >= prev.get("expires", 0):
            by_name[name] = c
    cookies_dict = {n: c.get("value", "") for n, c in by_name.items()}
    cookies_str = "; ".join(f"{n}={v}" for n, v in cookies_dict.items())
    return cookies_str, cookies_dict


def build_httpx_client(
    *,
    cookies_str: str,
    user_agent: str,
    referer: str,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Client:
    """Build a synchronous ``httpx.Client`` with sensible mining defaults.

    Default headers carry Cookie + User-Agent + Referer + Accept. Caller
    is expected to use it as a context manager (``with ... as client``)
    or call ``.close()`` to release the connection pool.
    """
    headers = {
        "User-Agent": user_agent,
        "Referer": referer,
        "Cookie": cookies_str,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if extra_headers:
        headers.update(extra_headers)
    return httpx.Client(
        headers=headers,
        timeout=_DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
