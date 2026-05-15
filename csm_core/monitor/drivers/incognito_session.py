"""百度 adapter 专用：per-fetch 无痕 BrowserContext。

为什么不复用 patchright_pool：那个池是为知乎设计的 `launch_persistent_context`
（持久 user-data-dir + 线程局部 Page + idle reaper）。百度任务每次 fetch
独立无痕、不带前次 cookie，跟那套 lifecycle 完全相反。

这里走 `browser.launch()` + `browser.new_context()`，离开 with 块后
context → browser → playwright 全部销毁，下次冷启重来。代价 2–4s 冷启，
换无前次指纹累积。

线程模型：每次调用都在调用者线程内启动 sync_playwright 并在同线程关闭。
不跨线程共享 handle —— monitor_loop 的 ThreadPoolExecutor 每个 task 在
单线程内完整跑完 fetch，没有 cross-thread 风险。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .patchright_pool import ensure_browsers_path

logger = logging.getLogger(__name__)


# Indirection 是为了让单元测试能 monkeypatch 一个 fake `sync_playwright`，
# 避开真启动 Chromium。
def _sync_playwright() -> Any:
    from patchright.sync_api import sync_playwright
    return sync_playwright()


@dataclass
class IncognitoSession:
    """一次 fetch 用的 patchright 资源句柄。

    Caller 只用到 `page` 和 `context`；其他句柄由 ContextManager 自己关。
    """
    page: Any
    context: Any
    browser: Any
    pw: Any


@contextmanager
def incognito_session(*, headless: bool) -> Iterator[IncognitoSession]:
    """启动一次无痕 patchright 会话。退出时 LIFO 全部销毁。

    Args:
        headless: True → 后台跑；False → 弹可见窗口（验证码升级用）。

    Yields:
        IncognitoSession，含 `.page`/`.context` 给 adapter 用。

    Raises:
        RuntimeError: patchright 未安装、Chromium 启动失败。
    """
    # 与 patchright_pool 共用 PLAYWRIGHT_BROWSERS_PATH 检测，确保 onefile 打包后
    # 也能找到 Chromium。
    ensure_browsers_path()

    pw = None
    browser = None
    context = None
    try:
        pw = _sync_playwright().start()
        # 真正的「无痕」: launch() 默认每次新建临时 profile dir，并在 close()
        # 时删除。比 launch_persistent_context 简单得多。
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
            ],
        )
        # new_context 真正给我们一个无痕上下文 —— cookie/storage 不会落盘。
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            # 不传 user_agent —— patchright Chromium 自带的 UA 跟它的 Client Hints
            # 是一致的；自己设会让 navigator.userAgent 与 userAgentData 错版本。
        )
        page = context.new_page()
        yield IncognitoSession(page=page, context=context, browser=browser, pw=pw)
    finally:
        # LIFO 关闭。每一层都包 try/except —— 一层炸了不能挡住下一层。
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("incognito context.close raised: %s", e)
        if browser is not None:
            try:
                browser.close()
            except Exception as e:
                logger.debug("incognito browser.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("incognito pw.stop raised: %s", e)
