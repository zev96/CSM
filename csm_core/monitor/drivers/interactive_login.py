"""Interactive cookie capture — user logs in via our Patchright window.

The cookie-from-real-Chrome flow (user grabs cookies from F12 → paste
into CSM) has one fundamental problem: the cookie was minted in user's
Chrome with its fingerprint, then re-used in our Patchright Chromium
with a different fingerprint. zhihu's risk engine sees the mismatch
and treats every request as suspicious — sometimes invalidating the
session within minutes.

This module flips that around: **let the user log in directly in our
Patchright Chromium**. The z_c0 token zhihu issues during that login
is tied to *our* Chromium's fingerprint, which is the same one we'll
use to scrape later. Match → no risk-engine flag → cookies last weeks
instead of hours.

Flow:
    1. Caller (HTTP endpoint) invokes ``capture_cookies_via_login``.
    2. We spin up a fresh Patchright Chromium window — NOT the shared
       scraping pool, because:
       a) the scraping pool may be in cooldown or running a fetch
       b) we want a clean state for login (no stale cookies)
       c) the window needs to stay open until the user is done
    3. The window navigates to the platform's login URL.
    4. We poll the context's cookie jar every second for the platform's
       known "I'm logged in" cookie (``z_c0`` for zhihu, ``SESSDATA``
       for bilibili, etc.).
    5. When that cookie appears, we wait one more second for any
       follow-up cookies (zhihu sets z_c0 *then* d_c0 *then* q_c1),
       read the whole jar for the platform domain, format as a
       semicolon-separated string, and save to ``platform_credentials``.
    6. The Patchright window is closed automatically.
    7. Caller gets back ``{id, label, cookie_count}``.

If the user takes too long (default 5 min), we time out and close the
window — the next attempt starts fresh.

Threading: this function blocks the calling thread for up to
``timeout_s`` seconds (until the user logs in or we time out). FastAPI
runs sync endpoints in a threadpool worker, so this is fine for the
HTTP layer. We do *not* reuse the shared monitor scraping pool — a
dedicated Playwright instance scoped to this function keeps the
window's lifecycle independent from anything else the sidecar is doing.
"""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlatformLoginSpec:
    """Per-platform knobs for the interactive login flow."""
    login_url: str
    #: Cookie name that, once present, means "user has finished logging in".
    #: We block until we see this name in the context jar.
    success_cookie_name: str
    #: Cookie domain to harvest (substring match — ``"zhihu"`` matches
    #: ``.zhihu.com`` and ``zhihu.com``).
    cookie_domain: str
    #: Human-friendly platform name for log/UI messages.
    display_name: str


# Registry of supported platforms. Add a new entry to enable login
# capture for additional platforms — no other code changes needed.
LOGIN_SPECS: dict[str, PlatformLoginSpec] = {
    "zhihu_question": PlatformLoginSpec(
        # /signin lands the user directly on the username/password tab.
        # zhihu also accepts QR code + phone-SMS from this same page.
        login_url="https://www.zhihu.com/signin",
        success_cookie_name="z_c0",
        cookie_domain="zhihu",
        display_name="知乎",
    ),
    "bilibili_comment": PlatformLoginSpec(
        login_url="https://passport.bilibili.com/login",
        success_cookie_name="SESSDATA",
        cookie_domain="bilibili",
        display_name="B 站",
    ),
    "douyin_comment": PlatformLoginSpec(
        # 抖音首页右上「登录」会弹出 modal —— 我们直接落首页让用户点
        # 登录按钮，比构造嵌套 modal URL 稳。检测到 sessionid 即成功。
        login_url="https://www.douyin.com/",
        success_cookie_name="sessionid",
        cookie_domain="douyin",
        display_name="抖音",
    ),
    "kuaishou_comment": PlatformLoginSpec(
        login_url="https://www.kuaishou.com/",
        success_cookie_name="kuaishou.server.web_st",
        cookie_domain="kuaishou",
        display_name="快手",
    ),
}


@dataclass
class LoginResult:
    """Outcome of one ``capture_cookies_via_login`` call."""
    success: bool
    cred_id: int | None
    cookie_count: int
    cookies_preview: str  # first 80 chars for logging / UI confirm
    error: str = ""


def capture_cookies_via_login(
    *,
    platform: str,
    label: str = "",
    timeout_s: float = 300.0,
    progress_callback: Callable[[str], None] | None = None,
) -> LoginResult:
    """Open a Patchright window, wait for user login, save cookies.

    Args:
        platform: key in ``LOGIN_SPECS``. Unknown platforms raise
            ``ValueError`` rather than silently choosing a default —
            mistyped platform names should fail loudly.
        label: human label for the saved row (e.g. "号-1"). Empty allowed.
        timeout_s: hard cap on user wait time. Default 5 minutes —
            generous because login may involve SMS / QR scan / 2FA.
        progress_callback: optional callback to surface state to the
            HTTP caller mid-flow (e.g. for SSE updates). Receives short
            status strings like "browser_opened" / "navigated" /
            "waiting_for_login" / "login_detected".

    Returns:
        ``LoginResult`` describing outcome. The function does NOT raise
        on user-timeout — that's a normal outcome (user gave up). Only
        infrastructure failures (Patchright won't launch) propagate.

    Raises:
        ValueError: unknown ``platform``.
        RuntimeError: Patchright unavailable (Chromium not installed,
            etc.). The HTTP layer surfaces this to the UI as a setup
            problem, not a login failure.
    """
    spec = LOGIN_SPECS.get(platform)
    if spec is None:
        raise ValueError(
            f"unknown platform {platform!r}; supported: {sorted(LOGIN_SPECS)}"
        )

    logger.info(
        "interactive login: starting capture for %s (label=%r, timeout=%.0fs)",
        spec.display_name, label, timeout_s,
    )
    _emit(progress_callback, "starting")
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "patchright is not installed; run `pip install patchright` and "
            "then `patchright install chromium`"
        ) from e

    # Critical for the PyInstaller-bundled sidecar: without this, patchright
    # tries to find Chromium inside its own _MEI<...>/patchright/driver/
    # extract dir and fails. Has to fire BEFORE sync_playwright().start()
    # so the Node subprocess inherits the corrected env.
    from . import patchright_pool
    patchright_pool.ensure_browsers_path()

    # Dedicated tempdir per login attempt — fully isolated from the
    # scraping pool's user_data_dir. We want this Chromium to start
    # cookie-free so the user sees a clean login screen, not a
    # half-authenticated state from a prior attempt.
    user_data_dir = str(
        Path(tempfile.gettempdir())
        / f"csm-login-{platform}-{int(time.time())}"
    )

    pw = None
    context = None
    page = None
    node_pid = 0
    try:
        # Step 1: start the Patchright driver subprocess. The most
        # common failure here is FileNotFoundError when the bundled
        # exe is missing patchright/driver/node.exe (PyInstaller spec
        # forgot collect_data_files("patchright")). Translate the bare
        # OSError into a RuntimeError so the HTTP route can map it to
        # a 503 with a useful "rebuild the bundle" message.
        try:
            pw = sync_playwright().start()
        except FileNotFoundError as e:
            raise RuntimeError(
                f"patchright driver not found ({e}); bundled sidecar is "
                "missing patchright/driver/node.exe — rebuild via "
                "`python scripts/build_sidecar.py --clean` "
                "(or run from system Python where the driver is intact)"
            ) from e
        except Exception as e:
            raise RuntimeError(f"patchright start() failed: {e!r}") from e
        # Same trick the scraping pool uses: stash Node subprocess PID
        # so the finally block can OS-kill the whole tree if the
        # graceful close hangs (e.g. user crashed the Chromium window
        # mid-evaluate and Playwright's IPC is wedged).
        try:
            node_pid = pw._impl_obj._connection._transport._proc.pid
        except Exception:
            node_pid = 0
        logger.info("interactive login: playwright started (node_pid=%d)", node_pid)
        # Same minimal launch args as the scraping pool — Patchright's
        # stealth does the heavy lifting; extra flags only add
        # fingerprint tells. See patchright_pool.py for the longer
        # version of this rationale.
        try:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1000,800",
                ],
                viewport={"width": 1000, "height": 800},
            )
        except Exception as e:
            raise RuntimeError(
                f"chromium launch failed: {e!r} — usually missing chromium "
                "binary; run `patchright install chromium`"
            ) from e
        _emit(progress_callback, "browser_opened")
        logger.info("interactive login: browser window opened")

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(spec.login_url, wait_until="domcontentloaded", timeout=30000)
        _emit(progress_callback, "navigated")

        logger.info(
            "interactive login: opened %s for %s (label=%r), waiting up to %.0fs",
            spec.login_url, spec.display_name, label, timeout_s,
        )

        # Poll the cookie jar. We could hook context.on('response') for
        # an event-driven detect, but polling every second is dead
        # simple and the cookie persists between checks — no race.
        deadline = time.monotonic() + timeout_s
        login_detected_at: float | None = None
        while time.monotonic() < deadline:
            # If the user manually closed the window, page.url raises.
            # That's a "user gave up" signal — treat it as timeout.
            try:
                _ = page.url
            except Exception:
                logger.info("interactive login: window closed by user")
                return LoginResult(
                    success=False, cred_id=None, cookie_count=0,
                    cookies_preview="", error="window_closed_by_user",
                )

            cookies_in_jar = context.cookies()
            success_seen = any(
                c.get("name") == spec.success_cookie_name
                and spec.cookie_domain in (c.get("domain") or "")
                for c in cookies_in_jar
            )
            if success_seen:
                if login_detected_at is None:
                    login_detected_at = time.monotonic()
                    _emit(progress_callback, "login_detected")
                    logger.info(
                        "interactive login: %s cookie detected, "
                        "waiting 1.5s for follow-up cookies",
                        spec.success_cookie_name,
                    )
                # Wait a beat for follow-up Set-Cookie headers (zhihu
                # sets z_c0 first, then drops d_c0 / q_c1 / __zse_ck in
                # the 200-500ms that follow). Grabbing the jar too
                # early gives an incomplete cookie set that may still
                # work but isn't ideal.
                if time.monotonic() - login_detected_at >= 1.5:
                    break
            time.sleep(1.0)
        else:
            logger.info("interactive login: timed out after %.0fs", timeout_s)
            return LoginResult(
                success=False, cred_id=None, cookie_count=0,
                cookies_preview="", error="timeout",
            )

        # Harvest. Filter to the platform's domain — we don't want to
        # save unrelated cookies (third-party analytics, etc.).
        final_jar = context.cookies()
        platform_cookies = [
            c for c in final_jar
            if spec.cookie_domain in (c.get("domain") or "")
        ]
        if not platform_cookies:
            # Shouldn't happen — we detected the success cookie above —
            # but defensively bail rather than save an empty row.
            return LoginResult(
                success=False, cred_id=None, cookie_count=0,
                cookies_preview="", error="no_cookies_after_detect",
            )

        cookies_text = _format_cookie_text(platform_cookies)
        # Read the UA the Chromium reported — store it on the row so
        # the curl_cffi fast path can mirror it (consistency between
        # the cookie's "issued under" UA and the UA used to send it
        # is one of zhihu's anti-bot checks).
        try:
            ua = page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            ua = ""

        cred_id = storage.add_credential(
            platform=platform,
            cookies_text=cookies_text,
            label=label,
            user_agent=ua,
        )
        logger.info(
            "interactive login: saved cookie row id=%d platform=%s label=%r "
            "cookies=%d ua=%r",
            cred_id, platform, label, len(platform_cookies), ua[:60],
        )
        _emit(progress_callback, "saved")
        return LoginResult(
            success=True,
            cred_id=cred_id,
            cookie_count=len(platform_cookies),
            cookies_preview=cookies_text[:80],
        )

    finally:
        # Always close, even on exception. Try graceful Playwright
        # cleanup first (will work because we're on the creating thread),
        # then fall through to OS-kill as a backstop for the case where
        # the user crashed the window mid-eval and Playwright's IPC is
        # stuck (otherwise the Chromium lingers until sidecar exits —
        # the same "browser doesn't close" complaint the scraping pool
        # had).
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("interactive login: context close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("interactive login: playwright stop raised: %s", e)
        if node_pid:
            # Import locally to avoid pulling patchright_pool at module
            # import time (interactive_login may be imported in test
            # contexts where the pool isn't ready).
            from . import patchright_pool
            patchright_pool._kill_process_tree(
                node_pid, label=f"interactive-login/node[{node_pid}]",
            )


def _format_cookie_text(cookies: list[dict[str, Any]]) -> str:
    """Render a Playwright cookie list as ``k=v; k=v; ...``.

    Matches the format the existing cookie pool already uses (the same
    format users paste from F12 → Application → Cookies). Keeps the
    downstream code path unchanged: this row gets read by CookieStore
    and parsed by ``_parse_cookies`` (split-on-semicolon) just like a
    hand-pasted entry.
    """
    parts: list[str] = []
    seen_names: set[str] = set()
    for c in cookies:
        name = c.get("name") or ""
        value = c.get("value") or ""
        if not name or name in seen_names:
            # Dedup by name — same name on different sub-domains
            # collapses to the most-specific one (which is whichever
            # Playwright returned first, usually the host-only cookie).
            continue
        seen_names.add(name)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def _emit(cb: Callable[[str], None] | None, state: str) -> None:
    if cb is None:
        return
    try:
        cb(state)
    except Exception:
        logger.debug("interactive login: progress callback raised", exc_info=True)
