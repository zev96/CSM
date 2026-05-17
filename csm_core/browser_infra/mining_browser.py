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
    """Best-effort: does the persistent profile have a key login cookie?

    Reads the SQLite cookie store directly because spinning a Chromium
    just to check this would be wasteful. The file may not exist yet
    (fresh profile) or may be locked (browser running) — both → False.
    """
    profile = _profile_dir_for(platform)
    cookies_db = profile / "Default" / "Cookies"
    if not cookies_db.exists():
        return False
    key_cookie = {
        "douyin": "sessionid",
        "bilibili": "SESSDATA",
        "kuaishou": "kuaishou.web.cp.api_st",
    }.get(platform)
    if not key_cookie:
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True, timeout=0.2)
        try:
            row = conn.execute(
                "SELECT 1 FROM cookies WHERE name=? LIMIT 1", (key_cookie,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # locked = Chromium running with this profile → assume valid
        return True
    except Exception as e:
        logger.debug("has_login_cookie[%s] read failed: %s", platform, e)
        return False
