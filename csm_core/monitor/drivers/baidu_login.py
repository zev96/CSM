"""百度账号登录态管理：登录 webview / 状态读取 / SERP 后置兜底。

跟 baidu_browser.py 配套：baidu_browser_session 提供 persistent context
contextmanager；本模块提供登录态的写入（open_login_window）+ 读取
（get_login_status）+ 运行时兜底（detect_login_required）。

profile lock：open_login_window 跟 baidu_keyword task 抢同一个
user_data_dir。caller 在 sidecar route 里先 has_active_baidu_task 409 拦截。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .patchright_pool import ensure_browsers_path


logger = logging.getLogger(__name__)


# ── SERP-time check ────────────────────────────────────────────────────


# 跳到登录墙的 URL 域名子串。跟 risk_detector._URL_PATTERNS 有交集但语义
# 不同：risk_detector 是 "百度风控触发" (captcha)，这里是 "百度要求登录"。
# 业务后果一样（task 暂停），但用户在 UI 上看到的提示文案不同。
_LOGIN_REDIRECT_HOSTS = (
    "wappass.baidu.com",
    "passport.baidu.com",
)

# SERP 返回 200 但页面内有"请登录"类文案 —— server-side session 失效，
# cookie 看起来还在但已经被服务端撤销。覆盖几种常见话术。
_LOGIN_PROMPT_PHRASES = (
    "请登录",
    "登录后查看",
    "登录后体验",
)


def detect_login_required(response: Any, page: Any) -> bool:
    """判断这次 SERP 响应是否实际把我们打回登录墙。

    SERP 后置兜底用 —— 主流程在 fetch 入口已经读过 BDUSS cookie，但
    server-side session 可能先于 cookie expires_at 失效（cookie 看着
    还在但服务端不认）。这时 SERP 会跳 passport / wappass，或 200 OK
    body 含"请登录"文案。

    Args:
        response: page.goto 的返回值，可能为 None（main-frame nav 时偶发）。
        page: patchright Page handle。content() 失败时 fail-soft。

    Returns:
        True = 命中登录墙；False = 正常 SERP。
    """
    # Layer 1: response.url 子串匹配 —— 最便宜的一层，先跑。
    try:
        url = getattr(response, "url", "") or ""
        for host in _LOGIN_REDIRECT_HOSTS:
            if host in url:
                return True
    except Exception:
        pass

    # Layer 2: page.content() 文本检查 —— cookie 还在但 server session
    # 失效时 SERP 仍 200 但 body 文案变了。
    #
    # 但这层最易误报：某条 organic 结果摘要里含"登录后查看/请登录"（很多站
    # 的引流文案）就会被判成"登录墙"，把整个任务暂停。所以先看 SERP 是否
    # 正常渲染出了结果 —— 有结果 = 词是摘要不是登录墙，跳过 Layer 2。真登录
    # 墙没有结果容器，Layer 2 照常生效。（复用 risk_detector 同一判据。）
    try:
        from .risk_detector import _serp_rendered_results
        if _serp_rendered_results(page):
            return False
    except Exception as e:
        logger.debug("detect_login_required serp-results probe raised: %s", e)
    try:
        html = page.content() if hasattr(page, "content") else ""
        for phrase in _LOGIN_PROMPT_PHRASES:
            if phrase in html:
                return True
    except Exception as e:
        # 不能让一个 content() 异常阻塞 SERP 解析。debug-log，返回 False。
        logger.debug("detect_login_required content() raised: %s", e)
        return False

    return False


# ── module-level indirection for monkeypatching in tests ──────────────


def _sync_playwright() -> Any:
    """Indirection so unit tests can monkeypatch a fake. Mirrors the
    same pattern in baidu_browser._sync_playwright."""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


def _default_user_data_dir() -> Path:
    """Same path as baidu_browser._default_user_data_dir — single profile
    shared between login window and fetch tasks."""
    from csm_sidecar.services import config_service
    return config_service.get_path().parent / "baidu_browser_profile"


_META_FILENAME = ".csm_login_meta.json"


# ── get_login_status ───────────────────────────────────────────────────


def get_login_status(user_data_dir: Path | None = None) -> dict[str, Any]:
    """读 persistent profile 看登录态。不弹窗。

    实现：launch_persistent_context(headless=True) 短时启动，读
    cookies("https://www.baidu.com/")，立刻关。开销 ~2s，settings 页
    打开时调一次能接受。

    BDUSS 不在 → logged_in=False。
    BDUSS 在但 expires < now → logged_in=False (cookie 已过期)。
    BDUSS 在且未过期 → logged_in=True，username 从 user_data_dir /
        ".csm_login_meta.json" 读取（open_login_window 成功时写入）。

    Returns:
        {"logged_in": bool, "username": str | None, "expires_at": str | None}
    """
    ensure_browsers_path()
    target_dir = user_data_dir or _default_user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()
        # headless 必须用完整 Chromium 的 executable_path —— 否则 Patchright
        # 走 headless 默认会找 chrome-headless-shell（未随包），启动直接抛
        # "Executable doesn't exist"，导致登录态读取永远失败 → UI 恒显未登录。
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=True,
            executable_path=pw.chromium.executable_path,
        )
        try:
            cookies = context.cookies("https://www.baidu.com/")
        except Exception as e:
            logger.debug("get_login_status cookies() raised: %s", e)
            cookies = []
        names = [c.get("name") for c in cookies]
        logger.info(
            "baidu login-status: read %d cookies (BDUSS=%s) from %s",
            len(cookies), "yes" if "BDUSS" in names else "no", target_dir,
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("get_login_status context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("get_login_status pw.stop raised: %s", e)

    return _status_from_cookies(cookies, target_dir)


def _status_from_cookies(
    cookies: list[dict[str, Any]], user_data_dir: Path,
) -> dict[str, Any]:
    """Cookie 列表 → status dict。pure logic，单独抽出便于测。"""
    bduss = next((c for c in cookies if c.get("name") == "BDUSS"), None)
    if bduss is None:
        return {"logged_in": False, "username": None, "expires_at": None}

    # expires = -1 表示 session cookie，对登录态来说视为有效（baidu 实际
    # 用 -1 标记长效凭据），expires_at 返回 None。
    expires = bduss.get("expires")
    if expires is not None and expires != -1 and expires < time.time():
        return {"logged_in": False, "username": None, "expires_at": None}

    expires_at: str | None = None
    if expires is not None and expires != -1:
        expires_at = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()

    username = _read_username(user_data_dir)
    return {"logged_in": True, "username": username, "expires_at": expires_at}


def _read_username(user_data_dir: Path) -> str | None:
    """Read .csm_login_meta.json. Missing file or parse failure → None."""
    meta_path = user_data_dir / _META_FILENAME
    try:
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        name = data.get("username")
        return name if isinstance(name, str) and name else None
    except Exception as e:
        logger.debug("read .csm_login_meta.json failed: %s", e)
        return None


# ── open_login_window ──────────────────────────────────────────────────


# Tunable in tests via monkeypatch
_POLL_INTERVAL_S = 3.0
# After BDUSS shows up, sleep this long so the rest of the login cookies
# (PTOKEN/STOKEN/PASS_TICKET) finish landing on disk before we close.
_POST_LOGIN_SETTLE_S = 2.0


def open_login_window(
    user_data_dir: Path | None = None,
    *,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """开一个可见 patchright headed 窗口让用户登录百度。

    流程：
    1. launch_persistent_context(headless=False) 在 baidu profile 上开窗
    2. page.goto("https://www.baidu.com/") + bring_to_front
    3. 每 _POLL_INTERVAL_S 秒 poll context.cookies，检测 BDUSS 是否出现
    4. 同时监听 BrowserContext "close" 事件（用户手动关窗）
    5. BDUSS 命中 → 等 _POST_LOGIN_SETTLE_S 让其他登录 cookie 落盘 → close
    6. 用户关窗 → 立即返回 cancelled
    7. timeout_s 达到 → 关窗 + 返回 timeout

    success 时写 user_data_dir / .csm_login_meta.json，供 get_login_status
    后续读取。

    Returns:
        {"status": "success" | "cancelled" | "timeout", "username": str | None}
    """
    ensure_browsers_path()
    target_dir = user_data_dir or _default_user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()
        # viewport + window-size 必须跟 baidu_browser.baidu_browser_session 完全
        # 对齐（1366×768）—— BDUSS 是绑到 fingerprint 的，两边 viewport 不一致
        # 时 baidu 会把后续 SERP 请求当作"被劫持的会话"，强制重新登录。
        # 不加 --blink-settings=imagesEnabled=false：登录窗口要能扫码 QR，关图
        # 会让 QR 加载不出来。等关闭后 fetch 那边再开 imagesEnabled=false，
        # 这层 fingerprint 差异 baidu 仅在 JS 探测时才看得到，SERP 请求阶段不
        # 影响 cookie 有效性。
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=False,
            viewport={"width": 1366, "height": 768},
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # User-closed flag — toggled via the context "close" event listener
        # below. _open_login_poll respects it.
        state = {"closed_by_user": False}
        def _on_close(_evt=None):
            state["closed_by_user"] = True
        try:
            context.on("close", _on_close)
        except Exception as e:
            # FakeContext in tests may not implement on(). Log + continue.
            logger.debug("context.on('close') not available: %s", e)

        try:
            page.goto("https://www.baidu.com/", wait_until="domcontentloaded")
            try:
                page.bring_to_front()
            except Exception:
                pass
        except Exception as e:
            logger.warning("open_login_window goto failed: %s", e)

        outcome = _open_login_poll(context, state, timeout_s)
        if outcome == "success":
            time.sleep(_POST_LOGIN_SETTLE_S)
            username = _fetch_username_from_passport(context)
            _write_login_meta(target_dir, username)
            return {"status": "success", "username": username}
        return {"status": outcome, "username": None}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("open_login_window context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("open_login_window pw.stop raised: %s", e)


def _open_login_poll(context: Any, state: dict[str, bool], timeout_s: int) -> str:
    """Poll until BDUSS appears, user closes window, or timeout. Returns
    one of: 'success', 'cancelled', 'timeout'."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if state.get("closed_by_user"):
            return "cancelled"
        try:
            cookies = context.cookies("https://www.baidu.com/")
        except Exception as e:
            logger.info("baidu login poll cookies() raised: %s", e)  # 原 debug→info
            cookies = []
        if any(c.get("name") == "BDUSS" for c in cookies):
            logger.info("baidu login poll: BDUSS detected (%d cookies)", len(cookies))
            return "success"
        time.sleep(_POLL_INTERVAL_S)
    return "timeout"


def _fetch_username_from_passport(context: Any) -> str | None:
    """Best-effort: hit baidu passport's logininfo endpoint inside the
    same context (cookies attached) to retrieve the username. Failure
    is non-fatal — success without a username still counts as logged in.
    """
    # passport API is unstable/private; defer real impl. Returning None
    # is fine — the frontend falls back to "已登录" without name.
    return None


def _write_login_meta(user_data_dir: Path, username: str | None) -> None:
    """Write the meta file get_login_status reads."""
    meta = {
        "username": username,
        "logged_in_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    try:
        (user_data_dir / _META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8",
        )
    except Exception as e:
        logger.warning("write .csm_login_meta.json failed: %s", e)
