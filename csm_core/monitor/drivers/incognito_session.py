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
from .risk_detector import detect_risk_by_url

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

        # ── Launch flags ────────────────────────────────────────────────
        # 1) 关图片加载：百度 SERP 抓取只需要 HTML/标题/URL，缩略图、Logo、
        #    资讯卡片图都用不到。`--blink-settings=imagesEnabled=false` 让
        #    Blink 引擎层直接跳过 image request —— 单次 fetch 能省 1-3s 网
        #    络时间，对一个 task 跑多个 SERP 的场景累计很可观。
        # 2) 「假隐藏」窗口（headless=True 时）：patchright 的 stealth fork
        #    不能真正 honor playwright `headless=True` —— 部分环境下 Chromium
        #    会照样弹窗（stealth 需要真实 GPU 上下文）。我们改成 headed +
        #    `--window-position=-32000,-32000` + `--start-minimized`，让窗
        #    口在虚拟桌面外，用户视觉上完全察觉不到。验证码升级时（外部
        #    传 `headless=False`）才用正常坐标，让用户能看到 / 滑滑块。
        launch_args: list[str] = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1366,768",
            "--blink-settings=imagesEnabled=false",
        ]
        effective_headless = headless
        if headless:
            # 始终以 headed 启动（stealth 才能工作），位置推到屏外。
            launch_args.extend([
                "--window-position=-32000,-32000",
                "--start-minimized",
            ])
            effective_headless = False

        # 真正的「无痕」: launch() 默认每次新建临时 profile dir，并在 close()
        # 时删除。比 launch_persistent_context 简单得多。
        browser = pw.chromium.launch(
            headless=effective_headless,
            args=launch_args,
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


# 老的 _BAIDU_CAPTCHA_URL_MARKERS 元组已迁入 risk_detector._URL_PATTERNS
# （4 层检测体系的 URL 子串层）。is_baidu_captcha_url 保留为向后兼容 shim；
# 新调用点应该直接用 detect_risk_by_url 或更全的 risk_detector.detect_risk()。


def is_baidu_captcha_url(url: str) -> bool:
    """True iff 落地 URL 看起来是百度的反爬验证码页。

    在 `page.goto` 之后立刻调一次 —— 命中说明已被百度拦下，要么走
    headless→可见升级，要么把当前 task 标 risk_control。

    向后兼容 shim：内部委托给 risk_detector.detect_risk_by_url。
    """
    return detect_risk_by_url(url) is not None
