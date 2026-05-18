"""Patchright browser pool — stealth-patched Playwright fork.

Why Patchright over DrissionPage as the default engine:
    - **Stealth out of the box.** Patchright is Playwright with the
      automated-Chrome fingerprints (CDP runtime ids, navigator.webdriver,
      worker handshakes) patched at the bundled-binary level. Vanilla
      Playwright trips zhihu's `/account/unhuman` wall within a few
      tabs; Patchright + a real cookie holds for thousands of requests.
    - **API stability.** Playwright's sync API hasn't churned in 2 years.
      DrissionPage 3.x→4.x changed selector syntax (`css:` prefix), the
      headless launch path, and the cookie API — every minor upgrade
      breaks something.

Why we still keep DrissionPage available:
    - Patchright bundles its own Chromium (`patchright install chromium`,
      ~170MB). Users on metered connections or air-gapped machines may
      prefer reusing their local Chrome (DrissionPage's strategy).
    - Fallback when Patchright ships a regression — user flips the
      engine setting in the UI and recovers without a code change.

**Thread model (important).** Playwright's sync API uses greenlets to
bridge to its async core, and a Playwright handle is bound to the OS
thread that created it (``Cannot switch to a different thread`` error
on any cross-thread call). The sidecar dispatches monitor tasks via
``ThreadPoolExecutor`` with named workers ``monitor-worker-N``, so a
naive process-wide singleton would crash the moment task #2 lands on
a different worker.

This module therefore keeps **one Playwright instance per worker
thread** via ``threading.local()``. Worst case: ``ThreadPoolExecutor``
opens N=4 workers → up to 4 Chromium processes running, ~600MB RAM.
The idle reaper closes each one after ``IDLE_SHUTDOWN_SECONDS`` of
inactivity, so a typical batch (a few tasks back-to-back, then idle)
only ever has 1–2 live at a time.

DrissionPage doesn't have this issue (it talks CDP over WebSocket,
thread-agnostic) which is why ``drission_pool`` stays as a single
process-wide singleton.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Stealth hardening ──────────────────────────────────────────────────────
# 抖音/快手/百家号风控查这些信号：navigator.webdriver、window.cdc_*、
# 缺少 Accept-Language、UA 不一致。统一在 pool 这层处理，所有 adapter 共享。

_VIEWPORT_BUCKETS = (
    {"width": 1280, "height": 800},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
)


# Per-thread sticky viewport cache —— 同一个 worker 线程跨 launch 保持
# 相同 viewport，避免"同账号跨会话突然换屏幕尺寸"的检测信号。
_thread_viewport: threading.local = threading.local()


def _pick_viewport() -> dict[str, int]:
    """Pick a viewport for this launch. Sticky per-thread so the same worker presents
    consistent screen dimensions across sequential launches (avoids the "single account
    oscillating between 3 viewports" detection signal).

    Different worker threads pick independently — that's intentional, gives some
    fingerprint diversification while preserving session-level continuity per worker."""
    cached = getattr(_thread_viewport, "value", None)
    if cached is not None:
        return cached
    chosen = random.choice(_VIEWPORT_BUCKETS)
    _thread_viewport.value = chosen
    return chosen


def _build_launch_args(viewport: dict[str, int] | None = None) -> list[str]:
    """Pool 启动 Chromium 时的统一 launch args。基础 --no-sandbox 系列 +
    反自动化探测 flag。

    注意：Patchright 在 CDP 层已经 patch 了 navigator.webdriver，
    --disable-blink-features=AutomationControlled 与之叠加在某些
    FingerprintJS 检测中会产生可检测组合，但仍有平台（百家号等）要求
    此 flag。综合权衡保留。

    viewport: 如果传入，启动加 --window-size=W,H 使 OS 窗口尺寸匹配
    viewport，保持 window.outerWidth ≈ window.innerWidth + chrome 真实
    浏览器关系。不传则 Chromium 用默认大小（可能与 viewport mismatch）。
    """
    args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    if viewport is not None:
        args.append(f"--window-size={viewport['width']},{viewport['height']}")
    return args


def _build_init_script() -> str:
    """每个 page navigate 前注入。屏蔽 webdriver 标记 + ChromeDriver 残留 +
    给 plugins / languages 假数据。这段 JS 由 Patchright 直接发给 Chromium 执行。"""
    return r"""Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
// 给 window.chrome 一个简单的 placeholder 对象 —— 真 Chrome 上这个是个非空 object，
// Patchright 不同版本对它处理不一致，我们补一层兜底
if (!window.chrome) {
    window.chrome = { runtime: {} };
}
// 屏蔽 ChromeDriver 注入的全局变量
for (const k of Object.keys(window)) {
    if (k.startsWith('cdc_') || k.startsWith('$cdc_')) {
        try { delete window[k]; } catch (e) {}
    }
}
"""


def _build_extra_headers() -> dict[str, str]:
    """Context 默认 extra_http_headers。仅设 Accept-Language —— 这是 Patchright
    默认 en-US、中文站点的真实 gap。

    sec-ch-ua / sec-ch-ua-mobile / sec-ch-ua-platform **故意不设**：HTTP header
    伪造的 sec-ch-ua 跟 JS 端 navigator.userAgentData.brands 报的真实 Chromium
    版本不一致，是 FingerprintJS 一眼能识别的 cheap signal（比命中 webdriver
    更严重）。让 Patchright 自然回应 Accept-CH 流程才一致。
    """
    return {
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


# ── /Stealth hardening ─────────────────────────────────────────────────────


#: Same default as drission_pool for consistency. See that file for the
#: trade-off discussion (30s = "feels closed" + cheap restart on cold
#: tick, vs the original 5 minutes that felt like a leak).
IDLE_SHUTDOWN_SECONDS = 30.0


_browsers_path_logged = False


def ensure_browsers_path() -> str | None:
    """Make sure Patchright can find its Chromium when running bundled.

    Symptom (only seen in PyInstaller onefile builds): ``launch_persistent_context``
    raises ``Executable doesn't exist at <_MEI>/patchright/driver/package/.local-browsers/...``.
    Cause: when patchright is unpacked into PyInstaller's ephemeral
    ``_MEI<random>/`` temp dir, the Node driver sees its own install
    looking "freshly installed" and resolves the browser cache to
    ``<driver>/.local-browsers/`` — which is empty, because
    ``patchright install chromium`` populated the user-wide cache at
    ``%LOCALAPPDATA%\\ms-playwright`` (not anywhere the bundle knows about).

    Fix: explicitly set ``PLAYWRIGHT_BROWSERS_PATH`` to that user-wide
    cache before any ``sync_playwright().start()`` call — both the
    monitor scraping pool and the interactive-login flow rely on this.

    Honors a user-provided ``PLAYWRIGHT_BROWSERS_PATH`` if already set
    (e.g. someone shipped a portable browser layout). Returns the path
    actually in effect, or ``None`` if we couldn't compute one (in
    which case patchright is left to its default behaviour).
    """
    global _browsers_path_logged
    existing = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if existing:
        return existing

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        candidate = Path(base) / "ms-playwright"
    elif sys.platform == "darwin":
        candidate = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        candidate = Path.home() / ".cache" / "ms-playwright"

    if not candidate.exists():
        # Don't set a non-existent path — patchright would then refuse
        # to fall through to its own discovery and we'd be worse off.
        if not _browsers_path_logged:
            logger.warning(
                "PLAYWRIGHT_BROWSERS_PATH not set and default %s doesn't exist — "
                "run `patchright install chromium` first",
                candidate,
            )
            _browsers_path_logged = True
        return None

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
    if not _browsers_path_logged:
        logger.info("PLAYWRIGHT_BROWSERS_PATH defaulted to %s", candidate)
        _browsers_path_logged = True
    return str(candidate)


@dataclass
class _ThreadState:
    """Per-thread Playwright resources. Lives in ``threading.local()``."""
    playwright: Any = None
    context: Any = None
    page: Any = None
    last_used: float = 0.0
    #: PID of the Node.js subprocess that hosts Patchright's driver.
    #: Killing this PID cascade-terminates every Chromium child (verified
    #: empirically — Playwright spawns Chromiums as children of Node).
    #: We track this because ``context.close()`` is greenlet-bound to
    #: the creating thread, so the cross-thread idle reaper can't call
    #: it. Direct OS-level kill via psutil is thread-agnostic.
    node_pid: int = 0
    #: Bumped each launch so the user_data_dir gets a fresh suffix.
    #: Killing Chromium abruptly leaves a profile-lock file behind, so
    #: re-using the same dir on next launch would fail. Cheap to
    #: increment, dir is in tempdir anyway.
    launch_seq: int = 0
    #: Set by the idle reaper (cross-thread) to ask the owning worker
    #: thread to finish closing on its next ``get_page()`` call.
    #:
    #: Why this two-step dance is needed:
    #:   - The reaper OS-kills Node + Chromium (frees RAM immediately,
    #:     browser window closes) — that part works cross-thread.
    #:   - But Playwright's sync API installed an asyncio
    #:     ``ProactorEventLoop`` on the worker thread when ``start()``
    #:     first ran. The reaper can't touch that loop from another
    #:     thread (it's bound to the worker's greenlet context).
    #:   - On the next ``get_page()`` call, the orphan loop still
    #:     exists; Playwright's next ``sync_playwright().start()`` sees
    #:     it via ``asyncio.get_running_loop()`` and bails with
    #:     "Sync API inside the asyncio loop" — that's the user-visible
    #:     bug we hit after the first idle-reap.
    #:   - Fix: when this flag is set, the owning thread calls
    #:     ``state.playwright.stop()`` on itself (same-thread → works)
    #:     before launching fresh. That cleanly disposes the loop.
    #:     Empirically ``pw.stop()`` returns in <1ms even when Node is
    #:     already dead — no hangs.
    close_requested: bool = False


_local = threading.local()

# Tracks every per-thread state so the global ``shutdown()`` / reaper
# can find and close them all. ``threading.local`` only gives the
# calling thread access to its own slot, but we need cross-thread
# cleanup at sidecar shutdown.
_registry_lock = threading.Lock()
_registry: dict[int, _ThreadState] = {}  # thread_ident → state

_chrome_path: str = ""
_idle_thread: threading.Thread | None = None
_stop_event = threading.Event()


def configure(chrome_path: str = "") -> None:
    """Set the Chrome executable path. Empty = use Patchright's bundled Chromium.

    Patchright differs from DrissionPage: if no path is set, it falls
    back to the Chromium it downloaded via ``patchright install``, not
    the user's system Chrome. That's the safer default (no profile-lock
    contention) so we don't auto-detect like Drission does.
    """
    global _chrome_path
    raw = (chrome_path or "").strip()
    if not raw:
        _chrome_path = ""
        return
    try:
        normalized = str(Path(raw).resolve())
        if Path(normalized).is_file():
            _chrome_path = normalized
            return
        logger.warning(
            "patchright chrome_path does not exist or is not a file: %r "
            "(after normalize: %r); falling back to bundled Chromium",
            raw, normalized,
        )
    except Exception:
        logger.exception("patchright chrome_path normalize failed for %r", raw)
    _chrome_path = ""


def get_page() -> Any:
    """Return the live Page for the calling thread, launching lazily.

    Each ``monitor-worker-N`` gets its own Playwright + Chromium. The
    page handle is cached in ``threading.local`` and reused across calls
    *on the same thread* — a different thread will spin up its own.

    Raises ``RuntimeError`` when Patchright is missing or Chromium can't
    launch. The most common first-run failure is missing Chromium
    binary; the message tells the user to run
    ``patchright install chromium``.
    """
    global _idle_thread
    state = getattr(_local, "state", None)
    if state is None:
        state = _ThreadState()
        _local.state = state
        # Register so the reaper / shutdown can sweep us up.
        with _registry_lock:
            _registry[threading.get_ident()] = state

    # Process any deferred close the reaper queued for us. We're on the
    # owning thread now, so Playwright's stop() is safe (greenlet match);
    # this disposes the orphan asyncio loop that would otherwise trip
    # the next sync_playwright().start() with "Sync API inside the
    # asyncio loop". See ``_ThreadState.close_requested`` for the long
    # explanation.
    if state.close_requested:
        _finish_close_on_owner_thread(state)

    state.last_used = time.monotonic()
    if state.page is not None:
        return state.page

    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "patchright is not installed; run `pip install patchright` and "
            "then `patchright install chromium` (or switch the monitor "
            "browser engine to 'drission' in Settings → Monitor)"
        ) from e

    # Bundled-exe browsers-path fix — see ensure_browsers_path() docstring.
    ensure_browsers_path()

    try:
        state.playwright = sync_playwright().start()
        # Stash the Node subprocess PID right after start — we'll use
        # it later to cross-thread-kill the whole driver tree when the
        # idle reaper fires. Internal attr but stable across Playwright
        # 1.x; if a future version breaks this we'd just lose cleanup
        # not the launch itself, so a graceful fallback (warn + continue)
        # is appropriate.
        try:
            state.node_pid = state.playwright._impl_obj._connection._transport._proc.pid
        except Exception:
            logger.warning(
                "patchright: cannot read Node subprocess PID — idle reaper "
                "won't be able to clean up Chromium until sidecar exits"
            )
            state.node_pid = 0
    except Exception as e:
        raise RuntimeError(f"patchright start() failed: {e!r}") from e

    # Independent user-data dir per launch — sharing one dir across
    # concurrent Chromium processes triggers ``ProfileInUseError``,
    # AND each launch needs a *different* dir from previous launches
    # on the same thread because abrupt termination (via the reaper's
    # cross-thread kill) leaves a profile-lock file behind. Thread id
    # + monotonic counter gives both isolation guarantees cheaply.
    state.launch_seq += 1
    user_data_dir = str(
        Path(tempfile.gettempdir())
        / f"csm-patchright-chrome-{threading.get_ident()}-{state.launch_seq}"
    )

    # Launch args, viewport and extra headers come from the stealth helpers
    # defined at the top of this module. They handle anti-fingerprint
    # defaults (AutomationControlled flag, randomised viewport, sec-ch-ua
    # header alignment, etc.) in one place so all adapters that use the
    # pool inherit them automatically.
    #
    # DO NOT override user_agent here. Patchright ships Chromium
    # ~131 (chromium-1217) and naturally reports a consistent
    # set of identity signals: navigator.userAgent ≈ 131,
    # navigator.userAgentData.brands ≈ 131, navigator.platform,
    # navigator.languages — all aligned. Overriding only the
    # HTTP UA + JS navigator.userAgent string (which is what
    # the ``user_agent`` kwarg does) leaves userAgentData and
    # the Client Hints headers still reporting the real version.
    # That mismatch is one of the cheapest bot-detection
    # signals there is: FingerprintJS flags it instantly, and
    # zhihu's risk engine bounces the session to /signin.
    #
    # If the user's harvested cookies came from a different
    # Chrome version (say Chrome 138), zhihu still treats them
    # as "valid token, slightly elevated risk" rather than
    # "valid token, definite automation". Soft signal > hard
    # signal.
    try:
        _viewport = _pick_viewport()
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": user_data_dir,
            # Patchright's stealth is supposed to make headless safe,
            # but zhihu's anti-bot has been seen to still flag fully
            # headless context. Headed = matches DrissionPage path.
            "headless": False,
            "args": _build_launch_args(viewport=_viewport),
            "viewport": _viewport,
            "extra_http_headers": _build_extra_headers(),
        }
        if _chrome_path:
            launch_kwargs["executable_path"] = _chrome_path
        state.context = state.playwright.chromium.launch_persistent_context(
            **launch_kwargs
        )
    except Exception as e:
        try:
            state.playwright.stop()
        except Exception:
            pass
        state.playwright = None
        detail = repr(e)
        hint = (
            " (configured chrome_path={!r})".format(_chrome_path)
            if _chrome_path
            else " (没设 chrome_path —— Patchright 会用自己下载的 Chromium，"
                 "第一次跑请先执行 `patchright install chromium`)"
        )
        raise RuntimeError(
            f"failed to launch Chromium: {detail}{hint}"
        ) from e

    # Inject stealth init_script on the context so every new page
    # (including the auto-opened tab below) gets the JS injection
    # before any navigation runs. Safe to call after launch.
    try:
        state.context.add_init_script(_build_init_script())
    except Exception as _e:
        logger.warning("pool: failed to inject init_script: %s", _e)

    # Reuse the auto-opened tab from launch_persistent_context — saves
    # one new_page() round trip on cold start.
    pages = state.context.pages
    state.page = pages[0] if pages else state.context.new_page()

    # Spin up the reaper once globally; it sweeps every registered
    # thread state, not just this one's.
    _ensure_reaper()
    logger.info(
        "Patchright Chromium launched on thread %s (pid=%d)",
        threading.current_thread().name, _safe_pid(state.context),
    )
    return state.page


def shutdown() -> None:
    """Tear down every thread's Playwright. Safe to call repeatedly.

    Iterates the registry rather than just the calling thread's slot —
    sidecar shutdown happens from the lifespan handler which runs on
    the main thread, but the live browsers live on worker threads.
    """
    _stop_event.set()
    with _registry_lock:
        thread_ids = list(_registry.keys())
        states = [_registry.pop(tid) for tid in thread_ids]
    for state in states:
        _close_state(state)
    # Best-effort: clear the calling thread's local pointer too.
    if hasattr(_local, "state"):
        delattr(_local, "state")


def set_cookies_for_domain(domain: str, cookies_text: str) -> None:
    """Inject ``k=v; k=v`` cookies into the calling thread's context.

    Must be called from the same thread that subsequently calls
    ``get_page()`` — Playwright handles are thread-bound.

    Sets a far-future ``expires`` so Playwright treats these as
    persistent rather than session cookies — important because zhihu's
    ``z_c0`` is checked on every API request and a session-only cookie
    would be tied to this Playwright session's lifetime in confusing
    ways. ``Secure=True`` matches how zhihu issues the originals (HTTPS
    only), and ``SameSite=Lax`` matches the browser default that zhihu
    serves them with — getting these flags wrong is a silent way for
    Playwright to drop the cookie on the next HTTPS request.
    """
    state = getattr(_local, "state", None)
    if state is None or state.context is None:
        logger.debug("patchright set_cookies_for_domain: no live context on this thread")
        return
    import time as _time
    far_future = int(_time.time()) + 30 * 86400  # +30 days
    cookies: list[dict[str, Any]] = []
    for piece in cookies_text.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        k, _, v = piece.partition("=")
        cookies.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": domain,
            "path": "/",
            "expires": far_future,
            "secure": True,
            "sameSite": "Lax",
        })
    if not cookies:
        return
    try:
        state.context.add_cookies(cookies)
    except Exception as e:
        logger.warning("patchright add_cookies failed on %s: %s", domain, e)


def clear_cookies_for_domain(domain_substring: str = "") -> None:
    """Wipe cookies matching ``domain_substring`` from this thread's context.

    Why this exists: ``launch_persistent_context`` keeps cookies across
    sidecar runs (that's its whole point — caches, page state). But
    that means stale auth cookies from a previous run (when we hit
    /unhuman or a login page) survive into the next launch, where
    they conflict with the cookie we're about to inject.

    Playwright's ``context.clear_cookies(domain=...)`` is the
    recommended way to scope this. Empty substring nukes everything,
    which we use when switching cookie pool accounts.
    """
    state = getattr(_local, "state", None)
    if state is None or state.context is None:
        return
    try:
        # Playwright accepts a `domain` filter to clear_cookies. We use
        # substring matching ourselves rather than relying on Playwright's
        # exact match — that way ".zhihu.com" / "zhihu.com" / "www.zhihu.com"
        # all match a single "zhihu" filter.
        if not domain_substring:
            state.context.clear_cookies()
            return
        existing = state.context.cookies()
        names_to_clear = [
            c for c in existing
            if domain_substring in (c.get("domain") or "")
        ]
        if not names_to_clear:
            return
        # No bulk delete-by-filter API; clear all then re-add the
        # non-matching ones. Cheap for our use case (<200 cookies).
        keep = [c for c in existing if domain_substring not in (c.get("domain") or "")]
        state.context.clear_cookies()
        if keep:
            state.context.add_cookies(keep)
    except Exception as e:
        logger.warning("patchright clear_cookies(%r) failed: %s", domain_substring, e)


def read_cookie_names(domain_substring: str = "") -> list[str]:
    """Return cookie names currently in this thread's context.

    Used by the adapter to verify after-the-fact that ``z_c0`` etc.
    actually landed in the browser context — the most reliable way to
    debug "I injected cookies but zhihu still shows login".
    """
    state = getattr(_local, "state", None)
    if state is None or state.context is None:
        return []
    try:
        existing = state.context.cookies()
    except Exception:
        return []
    if not domain_substring:
        return [c.get("name", "") for c in existing]
    return [
        c.get("name", "") for c in existing
        if domain_substring in (c.get("domain") or "")
    ]


# ── Reaper + helpers ──────────────────────────────────────────────────


def _ensure_reaper() -> None:
    """Lazily start the singleton idle reaper thread."""
    global _idle_thread
    if _idle_thread is not None and _idle_thread.is_alive():
        return
    _stop_event.clear()
    _idle_thread = threading.Thread(
        target=_idle_reaper, name="patchright-idle-reaper", daemon=True,
    )
    _idle_thread.start()


def _idle_reaper() -> None:
    """Free Chromium memory after IDLE_SHUTDOWN_SECONDS of inactivity.

    Cross-thread cleanup split into two phases (see
    ``_ThreadState.close_requested`` docstring for the full why):

    1. **Reaper does**: OS-kill the Node subprocess (cascade-kills
       every Chromium child → browser window closes, ~600MB RAM freed
       immediately). Mark ``state.close_requested = True``.

    2. **Owning worker thread does on its next** ``get_page()`` **call**:
       Run ``state.playwright.stop()`` to dispose the orphan asyncio
       event loop that Playwright installed on this thread. THEN
       launch a fresh browser.

    We keep the state in ``_registry`` after step 1 (instead of popping
    it like the old code) because the worker thread needs to find its
    own state on the next call. Popping it would orphan the close flag.

    On long sidecar uptime with many idle cycles, the worst-case is
    one stuck asyncio loop per worker thread between reap and next
    visit. That's a few MB and harmless. Once the worker visits, the
    loop gets cleaned up.
    """
    while not _stop_event.is_set():
        if _stop_event.wait(timeout=10.0):
            return
        now = time.monotonic()
        with _registry_lock:
            stale = [
                (tid, st) for tid, st in _registry.items()
                if st.page is not None
                and not st.close_requested
                and now - st.last_used >= IDLE_SHUTDOWN_SECONDS
            ]
        for tid, state in stale:
            logger.info(
                "Patchright idle on thread id=%d for %.0fs — OS-killing "
                "browser tree, deferring Playwright cleanup to worker",
                tid, IDLE_SHUTDOWN_SECONDS,
            )
            # OS-kill the Chromium tree NOW. This is cross-thread safe
            # because psutil just talks to the OS, no Playwright API.
            if state.node_pid:
                _kill_process_tree(
                    state.node_pid,
                    label=f"patchright/node[{state.node_pid}]",
                )
            # Flag for the owner to finish on its side. Note we leave
            # state.playwright as-is — the worker needs the handle to
            # call .stop() on its own thread. We only zero the page
            # and context so a stray get_page() race can't return a
            # dead handle.
            state.page = None
            state.context = None
            state.node_pid = 0
            state.close_requested = True


def _finish_close_on_owner_thread(state: _ThreadState) -> None:
    """Dispose Playwright on the owning worker thread.

    Called from ``get_page()`` after the reaper signaled close. Runs on
    the same thread that originally created the Playwright instance, so
    ``pw.stop()`` works (no "Cannot switch to a different thread"
    greenlet error). Empirically returns in <1ms even when Node is
    already gone — Playwright detects the dead transport and bails fast.
    """
    pw = state.playwright
    state.playwright = None  # zero early so a re-entrant call doesn't double-stop
    state.close_requested = False
    if pw is None:
        return
    try:
        pw.stop()
    except Exception as e:
        logger.debug("patchright pw.stop() on owner thread raised: %s", e)


def _close_state(state: _ThreadState) -> None:
    """Shut down one thread's Chromium tree from any caller thread.

    The straightforward ``state.context.close()`` / ``state.playwright.stop()``
    calls are greenlet-bound to the thread that created the handles —
    invoking them from the reaper thread raises
    ``Cannot switch to a different thread`` and the actual Chromium
    subprocess stays alive (silently leaked). The user noticed this as
    "抓完内容后浏览器不会关闭".

    Fix: bypass Playwright's cleanup entirely and OS-kill the Node
    subprocess that hosts Patchright's driver. Killing Node cascade-
    terminates every Chromium child because Chromium uses the Node
    pipe as its CDP transport — losing the pipe makes Chromium exit
    immediately. Verified empirically that one Node kill takes down
    all 9 child Chromium processes within a few seconds.

    We still attempt the Playwright cleanup as a *first* try in case
    we're being called from the owning thread (e.g. ``shutdown()``
    from sidecar lifespan running on the main thread but the state
    happens to belong to main thread). On cross-thread invocation
    those raise instantly into the bare ``except`` and we fall through
    to the OS-kill path that always works.
    """
    # First-try: clean Playwright shutdown. Works when caller thread
    # owns the state; otherwise raises and we fall through.
    if state.context is not None:
        try:
            state.context.close()
        except Exception as e:
            logger.debug("patchright context close raised (cross-thread expected): %s", e)
    if state.playwright is not None:
        try:
            state.playwright.stop()
        except Exception as e:
            logger.debug("patchright stop raised (cross-thread expected): %s", e)

    # Second-try: OS-level kill of the Node subprocess. Thread-agnostic,
    # works regardless of who's calling.
    if state.node_pid:
        _kill_process_tree(state.node_pid, label=f"patchright/node[{state.node_pid}]")

    state.page = None
    state.context = None
    state.playwright = None
    state.node_pid = 0


def _kill_process_tree(pid: int, *, label: str = "process") -> None:
    """OS-kill a Node PID and wait briefly for the cascade.

    Uses psutil for cross-platform termination semantics:
        - ``terminate()`` issues SIGTERM on Unix / Win32 TerminateProcess.
          Chromium handles this gracefully and flushes its profile (so
          a future re-use of the data dir is cleaner).
        - On timeout we escalate to ``kill()`` (SIGKILL / ungraceful).

    Failures here are logged but never re-raised — leaking a Chromium
    is bad UX but not worth crashing the reaper / shutdown path over.
    """
    try:
        import psutil
    except ImportError:
        logger.warning(
            "psutil not installed — cannot OS-kill %s; Chromium will "
            "linger until sidecar process exits",
            label,
        )
        return
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    except Exception as e:
        logger.debug("psutil.Process(%d) raised: %s", pid, e)
        return

    # Collect the whole tree BEFORE killing the root — once root dies,
    # children may become orphaned and re-parented to PID 1, breaking
    # the parent-child link we'd use to find them.
    try:
        descendants = proc.children(recursive=True)
    except Exception:
        descendants = []

    # Terminate root first (cascade often handles children), then mop up
    # any stragglers explicitly. The two-phase approach is robust
    # against the OS occasionally not cascading on Windows.
    for p in [proc] + descendants:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.debug("terminate %s pid=%d raised: %s", label, p.pid, e)

    # Wait up to ~3 seconds total for graceful exit. Chromium typically
    # dies within 500ms once Node is gone; we give it some slack for
    # heavy Win32 sessions.
    deadline = time.monotonic() + 3.0
    alive = [proc] + descendants
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if _safe_alive(p)]
        if alive:
            time.sleep(0.2)

    # Hard kill anyone still hanging on.
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.warning("hard-kill %s pid=%d raised: %s", label, p.pid, e)

    if alive:
        logger.info(
            "patchright cleanup for %s: killed root + %d descendants (some required SIGKILL)",
            label, len(descendants),
        )
    else:
        logger.info(
            "patchright cleanup for %s: terminated root + %d descendants cleanly",
            label, len(descendants),
        )


def _safe_alive(p: Any) -> bool:
    """``psutil.Process.is_running`` that swallows lookup errors."""
    try:
        return p.is_running() and p.status() != "zombie"
    except Exception:
        return False


def _safe_pid(context: Any) -> int:
    """Best-effort process id of the underlying Chromium, for logging."""
    try:
        return context.browser.process.pid  # type: ignore[no-any-return]
    except Exception:
        return 0
