"""DrissionPage singleton — used as the browser fallback for adapters.

Why singleton: launching a Chromium subprocess takes 2–5 seconds on
Windows. If every fetch on a slow path spins up its own page, a wave of
risk-controlled requests would bring the host machine to its knees. By
keeping one ``ChromiumPage`` alive across calls and idling it down after
``IDLE_SHUTDOWN_SECONDS`` of inactivity, the pool absorbs spikes without
holding 200MB of RAM forever.

Why DrissionPage and not Selenium / Playwright:
- Selenium needs ChromeDriver version-matching (the original Case-6 was
  brittle exactly because of this).
- Playwright bundles its own Chromium (~150MB into onedir).
- DrissionPage reuses the user's local Chrome at runtime, so onedir
  size stays sane and cookie/profile import works naturally.

This module is intentionally tolerant of import failure — DrissionPage
is an optional dependency in some deploys (a user might run only the
comment platforms which need only curl_cffi). Callers should treat
``get_page()`` raising ``RuntimeError`` as "fallback unavailable".
"""
from __future__ import annotations
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 浏览器实例空闲多久后自动回收。
#:
#: 30s 的取舍：
#:   - 单次「立刻监测」：用户跑一次抓完想看到窗口关掉，30s 内一定会关；
#:   - 定时批量（一次跑 N 个 zhihu 任务）：tick 之间通常 < 30s，浏览器
#:     仍然被复用，省下重启 Chrome 的 2-3s × N 任务的开销。
#:
#: 原来设的 300s（5 min）太长，用户体验上像「跑完不关」。Reaper 线程
#: 仍然每 30s 检查一次（见 _idle_reaper），所以实际回收延迟最多 60s。
IDLE_SHUTDOWN_SECONDS = 30.0


_lock = threading.Lock()
_page: Any = None  # DrissionPage.ChromiumPage when initialized
_last_used: float = 0.0
_chrome_path: str = ""
_idle_thread: threading.Thread | None = None
_stop_event = threading.Event()


def configure(chrome_path: str = "") -> None:
    """Set the Chrome executable path. Empty string = auto-detect.

    用户手动填路径时偶尔会写成双反斜杠（误以为要 JSON 转义），导致
    `C:\\\\Program Files\\\\...` 这种"四反斜杠"在内存里是 `C:\\Program...`
    四个分隔字符 Windows 不认。这里用 ``Path`` 走一遍规范化：单/双
    反斜杠都吃；不存在的路径就丢回空字符串，触发自动检测兜底。
    """
    global _chrome_path
    raw = (chrome_path or "").strip()
    if not raw:
        _chrome_path = ""
        return
    try:
        from pathlib import Path
        normalized = str(Path(raw).resolve())
        if Path(normalized).is_file():
            _chrome_path = normalized
            return
        # 文件不存在 —— 可能用户写错了；记一行日志，走自动检测
        logger.warning(
            "configured chrome_path does not exist or is not a file: %r"
            " (after normalize: %r); falling back to auto-detect",
            raw,
            normalized,
        )
    except Exception:
        logger.exception("chrome_path normalize failed for %r", raw)
    _chrome_path = ""


def get_page() -> Any:
    """Return the live ChromiumPage, launching it lazily if needed.

    Raises RuntimeError if DrissionPage isn't installed or Chrome can't
    be launched. The caller is expected to fall back to "report failed"
    in that case rather than try to keep going.
    """
    global _page, _last_used, _idle_thread
    with _lock:
        _last_used = time.monotonic()
        if _page is not None:
            return _page
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except ImportError as e:
            raise RuntimeError(
                "DrissionPage is not installed; browser fallback unavailable"
            ) from e
        opts = ChromiumOptions()
        # Prefer headless to keep the desktop quiet, but if the user has
        # configured a non-default Chrome path we honor it.
        if _chrome_path:
            opts.set_browser_path(_chrome_path)
        # 关键：用一个独立的 user-data-dir + 一个空闲端口启动 headless 实例。
        # 如果不指定，DrissionPage 会用 Chrome 默认 profile 目录，跟用户
        # 平时浏览的 Chrome 撞 user data lock，启动失败后会 fallback 到
        # "请连 9222" 那个 BrowserConnectError —— 90% 的"无法启动 Chromium"
        # 都是这个原因。每次进程独立目录，规避锁；用空目录而非真实 profile，
        # 也避免污染用户的浏览器历史/cookie。
        import tempfile
        user_data_dir = str(Path(tempfile.gettempdir()) / "csm-drission-chrome")
        try:
            opts.set_user_data_path(user_data_dir)
        except AttributeError:
            # DrissionPage 4.x 接口名 vs 3.x：set_paths 兜底
            try:
                opts.set_paths(user_data_path=user_data_dir)
            except Exception:
                logger.warning(
                    "DrissionPage: cannot set user_data_path; if user has Chrome open "
                    "the launch may fail with profile lock contention"
                )
        # 让 DrissionPage 自己挑空端口，而不是死磕 9222
        try:
            opts.auto_port()
        except AttributeError:
            pass
        # 不用 headless ——
        # 1) Chrome 148+ 下 `--headless=new` 跟 DrissionPage 4.1.1.2 撞 CDP
        #    WebSocket 握手 404 错误（实测）
        # 2) 老 `--headless` 能启动，但 zhihu 2024+ 的反爬会精准识别这种
        #    模式 → 跳"/account/unhuman" 验证墙，抓不到任何内容
        # 可见 Chrome 窗口反爬通过率高得多，代价是桌面会闪一下窗口。
        # 想要彻底无窗体可以在设置里关掉知乎监测、改用第三方抓取。
        opts.set_argument("--disable-blink-features=AutomationControlled")
        opts.set_argument("--no-sandbox")
        opts.set_argument("--disable-dev-shm-usage")
        # 缩小窗口减少视觉干扰（用户能看到但不抢焦点）
        opts.set_argument("--window-size=1000,700")
        # 关图片加载 —— 知乎答案页 SSR 完 N 张大图，下载耗 10-30s，对
        # 排名抓取毫无用处。`--blink-settings=imagesEnabled=false` 让浏览器
        # 引擎层根本不发 image request；外加 DrissionPage 的 no_imgs(True)
        # 双重保险。命中率比 prefs / extension 路径稳。
        opts.set_argument("--blink-settings=imagesEnabled=false")
        try:
            opts.no_imgs(True)
        except AttributeError:
            # 旧版 DrissionPage 没 no_imgs，前面 --blink-settings 已经够用
            pass
        # User-Agent 跟实际 Chrome 大版本对齐 —— UA 跟 navigator 暴露的
        # 版本号不一致也是反爬识别点之一
        opts.set_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        )
        try:
            _page = ChromiumPage(opts)
        except Exception as e:
            # DrissionPage 在自动检测 chrome.exe 失败后会再尝试 connect 到
            # 9222 端口，再失败时抛出一段多行中文错误。原来的 f"{e}" 经常
            # 把 message 折成空串；用 repr 兜底拿到异常类型 + 完整 message，
            # 配上 chrome_path 提示，方便用户定位是路径问题还是没装 Chrome。
            detail = str(e).strip() or repr(e)
            hint = (
                f" (configured chrome_path={_chrome_path!r})"
                if _chrome_path
                else " (chrome_path 未配置 —— DrissionPage 自动检测，"
                     "如果 Chrome 装在非默认路径请到「设置 → 监测 → Chrome 路径」手填)"
            )
            raise RuntimeError(
                f"failed to launch Chromium: {detail}{hint}"
            ) from e
        # Spin up the idle reaper on first launch.
        if _idle_thread is None or not _idle_thread.is_alive():
            _stop_event.clear()
            _idle_thread = threading.Thread(
                target=_idle_reaper, name="drission-idle-reaper", daemon=True
            )
            _idle_thread.start()
        logger.info("DrissionPage Chromium launched (headless)")
        return _page


def shutdown() -> None:
    """Tear down the live page, if any. Safe to call repeatedly.

    Used at app exit and from the idle reaper. After shutdown the next
    ``get_page()`` will pay the launch cost again — that's intentional.
    """
    global _page, _idle_thread
    with _lock:
        if _page is not None:
            try:
                _page.quit()
            except Exception as e:
                logger.warning("DrissionPage shutdown raised: %s", e)
            _page = None
        _stop_event.set()


def set_cookies_for_domain(domain: str, cookies_text: str) -> None:
    """Apply a `key=value; key=value` cookie string to ``domain``."""
    page = get_page()
    cookies: list[dict[str, str]] = []
    for piece in cookies_text.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        k, _, v = piece.partition("=")
        cookies.append({"name": k.strip(), "value": v.strip(), "domain": domain})
    try:
        page.set.cookies(cookies)
    except Exception as e:
        logger.warning("failed to set cookies on %s: %s", domain, e)


def _idle_reaper() -> None:
    """Background thread that quits Chromium after a quiet period."""
    while not _stop_event.is_set():
        # 跟新的 IDLE_SHUTDOWN_SECONDS=30s 配套，poll 间隔降到 10s 让
        # 实际关闭最多比目标延迟 10s（30 + 10 = 40s 内一定关）。原来
        # 30s 间隔配 5 min 阈值是合理的，配 30s 阈值就太粗了。
        if _stop_event.wait(timeout=10.0):
            return
        with _lock:
            if _page is None:
                continue
            if time.monotonic() - _last_used >= IDLE_SHUTDOWN_SECONDS:
                logger.info(
                    "DrissionPage idle for %.0fs — shutting down to free RAM",
                    IDLE_SHUTDOWN_SECONDS,
                )
                try:
                    _page.quit()
                except Exception as e:
                    logger.warning("DrissionPage idle shutdown raised: %s", e)
                # Fall-through: clear state and let the loop exit; the
                # next get_page() will start a new reaper thread.
                _set_page_none()
                return


def _set_page_none() -> None:
    """Helper used by the reaper that already holds _lock."""
    global _page
    _page = None
