"""GEO RPA 持久档会话 + 登录管理。

- rpa_page(platform): 采集用——开持久档页面、用完关（复用 mining_browser.launched_page）。
- open_login(platform): 有头窗让用户登录，轮询 DOM 登录态。
- login_status(platform): 无头快查登录态。
profile 落 browser_profiles/geo_<platform>/，与 mining/baidu 隔离。
"""
from __future__ import annotations
import contextlib
import logging
import time
from typing import Any, Iterator

from csm_core.browser_infra.mining_browser import launched_page, _profile_dir_for
from csm_core.browser_infra.patchright_pool import ensure_browsers_path
from csm_core.monitor.geo.providers.rpa._flow import is_logged_in_html
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 2000


@contextlib.contextmanager
def rpa_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """采集用持久档页面。geo_ 前缀隔离命名空间；monitor-cookie 注入对 geo_* 无操作。"""
    with launched_page(f"geo_{platform}", headless=headless) as page:
        yield page


def login_status(platform: str) -> dict[str, Any]:
    """无头快查登录态。返回 {"logged_in": bool}；任何失败降级 False。"""
    spec = SITES.get(platform)
    if spec is None:
        return {"logged_in": False, "error": f"未知 RPA 平台: {platform}"}
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        return {"logged_in": False, "error": "patchright 未安装"}
    ensure_browsers_path()
    user_data_dir = str(_profile_dir_for(f"geo_{platform}"))
    pw = None
    context = None
    try:
        pw = sync_playwright().start()
        # headless 必须用完整 Chromium 的 executable_path（同 baidu_login）——
        # 否则 patchright 找 chrome-headless-shell（未随包），启动即抛。
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=True,
            executable_path=pw.chromium.executable_path,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        html = page.content()
        logged_in = is_logged_in_html(
            html, logged_in_sel=spec.logged_in_sel, logged_out_sel=spec.logged_out_sel)
        logger.info("[geo-rpa][%s] login-status logged_in=%s", platform, logged_in)
        return {"logged_in": logged_in}
    except Exception as e:
        logger.warning("[geo-rpa][%s] login_status raised: %s", platform, e)
        return {"logged_in": False, "error": str(e)}
    finally:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()


def open_login(platform: str, *, timeout_s: int = 300) -> dict[str, Any]:
    """有头窗让用户登录，轮询 DOM 登录态。
    返回 {"status": "success"|"cancelled"|"timeout"|"error"}。持久档自动存 cookie。"""
    spec = SITES.get(platform)
    if spec is None:
        return {"status": "error", "error": f"未知 RPA 平台: {platform}"}
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "error": "patchright 未安装"}
    ensure_browsers_path()
    user_data_dir = str(_profile_dir_for(f"geo_{platform}"))
    pw = None
    context = None
    try:
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1100,820"],
            viewport={"width": 1100, "height": 820},
        )
        page = context.pages[0] if context.pages else context.new_page()
        state = {"closed": False}
        with contextlib.suppress(Exception):
            context.on("close", lambda *_: state.update(closed=True))
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
        with contextlib.suppress(Exception):
            page.bring_to_front()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if state["closed"]:
                return {"status": "cancelled"}
            try:
                html = page.content()
            except Exception as e:
                logger.debug("[geo-rpa][%s] page.content() raised (treat as 用户关窗): %s", platform, e)
                return {"status": "cancelled"}  # context 没了 = 用户关窗
            if is_logged_in_html(html, logged_in_sel=spec.logged_in_sel,
                                 logged_out_sel=spec.logged_out_sel):
                page.wait_for_timeout(1500)  # 等其余 cookie 落盘
                logger.info("[geo-rpa][%s] login success", platform)
                return {"status": "success"}
            page.wait_for_timeout(_POLL_INTERVAL_MS)
        return {"status": "timeout"}
    except Exception as e:
        logger.warning("[geo-rpa][%s] open_login raised: %s", platform, e)
        return {"status": "error", "error": str(e)}
    finally:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()
