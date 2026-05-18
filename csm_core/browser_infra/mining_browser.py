"""Thin adapter: mining module's browser access via the shared patchright_pool.

After PR 2b Task 6, mining_browser.launched_page is a thin adapter over
``patchright_pool`` instead of a self-contained launcher.  Mining therefore
inherits the pool's full stealth hardening (init_script, randomised viewport,
--window-size pairing, Accept-Language header, AutomationControlled flag) that
monitor adapters also benefit from.

Callers keep the same API::

    with mining_browser.launched_page("douyin") as page:
        ...

``_inject_monitor_cookies`` is still called at acquire-time so per-platform
credentials from monitor.db are available to mining pages.

``_kill_process_tree`` and ``configure_profile_root`` are retained for
backwards compatibility (lifespan.py still calls ``configure_profile_root``
on startup; _kill_process_tree is imported from patchright_pool and might be
used by other callers).
"""
from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any, Iterator

from csm_core.browser_infra.patchright_pool import (
    ensure_browsers_path,
    _kill_process_tree,
)

logger = logging.getLogger(__name__)


_PROFILE_ROOT_DEFAULT = "browser_profiles"
_profile_root: Path | None = None


def configure_profile_root(path: Path) -> None:
    """No-op after Task 6: mining now shares the pool's user_data_dir.

    Retained so sidecar lifespan.py (which calls this on startup) doesn't
    need to be changed. The argument is accepted but not used.
    """
    # Previously: created per-platform browser_profiles/<platform> dirs and
    # saved the root so launched_page could resolve them.  After the Task 6
    # refactor, the pool manages its own tempdir-based user_data_dir — mining
    # no longer maintains separate persistent profiles.
    global _profile_root
    _profile_root = Path(path)  # keep the value; callers may read it


def _profile_dir_for(platform: str) -> Path:
    """Retained for reference; no longer called by launched_page after Task 6."""
    if _profile_root is None:
        raise RuntimeError(
            "mining_browser profile root not configured — call configure_profile_root(...) first"
        )
    p = _profile_root / platform
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextlib.contextmanager
def launched_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """Context-managed Patchright Page acquired from the shared patchright_pool.

    After PR 2b Task 6, mining no longer maintains its own per-platform browser
    profile.  Instead it borrows from the same ``patchright_pool`` that monitor
    adapters use, inheriting:

    - Stealth hardening (init_script, --window-size pairing, viewport
      randomisation, Accept-Language header, AutomationControlled flag)
    - User-agent consistency per worker thread
    - Shared cookie state across launches on the same thread

    Cookies for this platform are still injected from monitor.db at acquire
    time via ``_inject_monitor_cookies(context, platform)``.

    Note on ``headless``: patchright_pool always launches headed (headless=False)
    because zhihu/douyin risk engines flag fully-headless contexts even with
    Patchright's stealth patches.  The ``headless`` parameter is accepted here
    for API compatibility but has no effect on the underlying pool launch.
    """
    from csm_core.browser_infra import patchright_pool

    # Acquire a page from the pool.  The pool is thread-local: same worker
    # thread → same Chromium instance reused across calls.  Different worker
    # threads each get their own isolated Chromium.
    page = patchright_pool.get_page()
    try:
        # Re-inject monitor cookies for this platform on every acquire — the
        # user may have refreshed credentials via 监控中心 → 凭据管理 since the
        # pool last launched.  If no credential exists this is a silent no-op.
        try:
            n = _inject_monitor_cookies(page.context, platform)
            if n:
                logger.info(
                    "mining_browser[%s] injected %d cookies from monitor DB",
                    platform, n,
                )
        except Exception as e:
            logger.warning("mining_browser[%s] cookie injection failed: %s", platform, e)
        yield page
    finally:
        # Pool owns the page lifecycle — idle reaper and shutdown() handle
        # teardown.  Do not close the page here or pool state becomes corrupt.
        pass


def has_login_cookie(platform: str) -> bool:
    """Does monitor.db have an enabled credential for this platform?

    Mining reuses the cookies that the user already configured in 监控中心
    (via the existing interactive-login flow or cookie-paste UI). That's
    the only login surface — mining doesn't maintain its own per-platform
    profile credentials.

    The platform name maps to monitor's TaskType naming convention:
      - "bilibili" → "bilibili_comment"
      - "douyin"   → "douyin_comment"
      - "kuaishou" → "kuaishou_comment"
    """
    cred_type = _MONITOR_CRED_TYPE.get(platform)
    if not cred_type:
        return False
    try:
        from csm_core.monitor import storage as monitor_storage
        conn = monitor_storage.get_conn()
        row = conn.execute(
            "SELECT 1 FROM platform_credentials "
            "WHERE platform=? AND enabled=1 LIMIT 1",
            (cred_type,),
        ).fetchone()
        return row is not None
    except Exception as e:
        logger.debug("has_login_cookie[%s] monitor DB lookup failed: %s", platform, e)
        return False


_MONITOR_CRED_TYPE = {
    "bilibili": "bilibili_comment",
    "douyin": "douyin_comment",
    "kuaishou": "kuaishou_comment",
}

# Each cookie gets injected once per domain in this list. monitor stores
# cookies as flat ``k=v;`` text without the original Set-Cookie domain
# attribute, so we re-inject every cookie to every plausible domain. The
# browser will silently drop a cookie on a request whose host doesn't
# match — there's no harm in over-injecting.
_COOKIE_DOMAINS = {
    "bilibili": (".bilibili.com", ".bilibili.cn"),
    "douyin": (".douyin.com", ".iesdouyin.com", ".snssdk.com"),
    "kuaishou": (
        ".kuaishou.com",            # main www
        "id.kuaishou.com",          # SSO host (where passToken originated)
        "www.kuaishou.com",         # explicit www (some servers reject .domain wildcard)
        "live.kuaishou.com",        # live subdomain
    ),
}


def _inject_monitor_cookies(context: Any, platform: str) -> int:
    """Pull the most-recently-used enabled credential from monitor.db and
    inject its cookies into the patchright browser ``context``.

    Returns the number of cookies injected (0 if none / config error).

    The cookies_text column stores a ``k=v; k=v`` string captured either
    by monitor's interactive-login flow or pasted from the user's daily
    Chrome (via 监控中心 → 凭据管理). We parse it the same way
    patchright_pool.set_cookies_for_domain does — Secure=True + SameSite=Lax,
    far-future expires so they survive the Chromium session boundary.
    """
    cred_type = _MONITOR_CRED_TYPE.get(platform)
    domains = _COOKIE_DOMAINS.get(platform, ())
    if not cred_type or not domains:
        return 0
    try:
        from csm_core.monitor import storage as monitor_storage
        conn = monitor_storage.get_conn()
        row = conn.execute(
            "SELECT cookies_text FROM platform_credentials "
            "WHERE platform=? AND enabled=1 "
            "ORDER BY last_used_at DESC NULLS LAST, id DESC LIMIT 1",
            (cred_type,),
        ).fetchone()
    except Exception as e:
        logger.warning("_inject_monitor_cookies[%s] DB lookup failed: %s", platform, e)
        return 0
    if row is None or not row[0]:
        return 0
    cookies_text = row[0]

    import time as _time
    far_future = int(_time.time()) + 30 * 86400  # +30 days
    parsed: list[tuple[str, str]] = []
    for piece in cookies_text.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        k, _, v = piece.partition("=")
        parsed.append((k.strip(), v.strip()))
    if not parsed:
        return 0

    cookies: list[dict[str, Any]] = []
    for domain in domains:
        for k, v in parsed:
            cookies.append({
                "name": k,
                "value": v,
                "domain": domain,
                "path": "/",
                "expires": far_future,
                "secure": True,
                # SameSite=None lets the cookie travel on cross-domain XHR
                # (auth-bearing fetches against id.kuaishou.com from a www
                # page, for example); Secure=True is required for None.
                "sameSite": "None",
            })
    if not cookies:
        return 0
    try:
        context.add_cookies(cookies)
    except Exception as e:
        logger.warning("_inject_monitor_cookies[%s] add_cookies raised: %s", platform, e)
        return 0
    return len(cookies)
