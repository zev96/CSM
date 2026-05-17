"""Persistent-profile Patchright launcher for the mining module.

Differs from ``patchright_pool``:

- One profile **per platform**, stable across launches → cookies survive.
- Caller drives the lifecycle (open → search → close); no thread-local
  caching, no idle reaper. Mining tasks are 5-10 min batches, not
  many-shot tasks like monitor, so the pool model doesn't help.
- Headed by default — see spec section 2 (browser mode lock).

Shares two helpers with ``patchright_pool``: ``ensure_browsers_path()``
and ``_kill_process_tree()``. We import them by string to avoid coupling
mining to monitor's pool wholesale.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
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
    """Tell the launcher where to put per-platform user_data_dirs.

    Typically called once at sidecar startup with ``<config_dir>/browser_profiles``.
    """
    global _profile_root
    _profile_root = Path(path)
    _profile_root.mkdir(parents=True, exist_ok=True)


def _profile_dir_for(platform: str) -> Path:
    if _profile_root is None:
        raise RuntimeError(
            "mining_browser profile root not configured — call configure_profile_root(...) first"
        )
    p = _profile_root / platform
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextlib.contextmanager
def launched_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """Context-managed Patchright Page for one mining batch.

    On exit: OS-kills the Chromium tree (cross-thread-safe path, same
    technique as patchright_pool's reaper). Profile cookies are persisted
    by Chromium before the kill cascade because launch_persistent_context
    flushes on context.close() — but cross-thread close raises, so we
    do a best-effort close-then-kill: graceful close runs on the owning
    thread, then we kill to guarantee teardown.
    """
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "patchright not installed; run `pip install patchright` and "
            "`patchright install chromium`"
        ) from e

    ensure_browsers_path()
    user_data_dir = str(_profile_dir_for(platform))

    pw = sync_playwright().start()
    node_pid = 0
    try:
        try:
            node_pid = pw._impl_obj._connection._transport._proc.pid
        except Exception:
            logger.warning(
                "mining_browser[%s]: cannot read node pid — graceful kill only", platform
            )

        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1000,700",
        ]
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=launch_args,
            viewport={"width": 1000, "height": 700},
        )
        pages = context.pages
        page = pages[0] if pages else context.new_page()
        logger.info(
            "mining_browser[%s] launched (profile=%s, node_pid=%d)",
            platform, user_data_dir, node_pid,
        )
        # Inject cookies from monitor.db platform_credentials. This is the
        # supported login surface — monitor's "interactive login" or
        # cookie-paste flow already populates these for douyin/bilibili/
        # kuaishou. Mining no longer needs its own login UX; users just
        # configure cookies once in 监控中心 → 凭据管理 and we ride along.
        try:
            n = _inject_monitor_cookies(context, platform)
            if n:
                logger.info(
                    "mining_browser[%s] injected %d cookies from monitor DB", platform, n,
                )
        except Exception as e:
            logger.warning("mining_browser[%s] cookie injection failed: %s", platform, e)
        try:
            yield page
        finally:
            try:
                context.close()
            except Exception as e:
                logger.debug("mining_browser[%s] context.close raised: %s", platform, e)
    finally:
        try:
            pw.stop()
        except Exception as e:
            logger.debug("mining_browser[%s] pw.stop raised: %s", platform, e)
        if node_pid:
            _kill_process_tree(node_pid, label=f"mining-browser[{platform}]")


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
