"""百度 adapter 专用：持久 BrowserContext（CSM 自有 profile）。

替代原 incognito_session 的"真无痕每次冷启"模式。改用 patchright 的
launch_persistent_context + 我们自己的 user_data_dir，让 BAIDUID /
BIDUPSID cookie 跨 task 累积 —— 这是把百度风控从「keyword #0 就 403」
拉回去的核心。

profile lock：同一时刻只能一个 instance 持有同一 user_data_dir。由
rate_limit.configure_concurrency(baidu_keyword, 1) 强制百度任务串行
保证。

线程模型：每次调用都在调用者线程内启动 sync_playwright 并在同线程关闭。
不跨线程共享 handle —— monitor_loop 的 ThreadPoolExecutor 每个 task 在
单线程内完整跑完 fetch，没有 cross-thread 风险。
"""
from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .patchright_pool import ensure_browsers_path

logger = logging.getLogger(__name__)


def _sync_playwright() -> Any:
    """Indirection 给单测 monkeypatch 用，避开真启 Chromium。"""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


@dataclass
class BaiduBrowserSession:
    """一次 fetch 用的 patchright 资源句柄。

    与原 IncognitoSession 的区别：persistent context 没有独立 browser
    handle（launch_persistent_context 把 launch+new_context 融合成一个
    调用），所以只暴露 page / context / pw。
    """
    page: Any
    context: Any
    pw: Any


@contextmanager
def baidu_browser_session(
    *, headless: bool, user_data_dir: Path | None = None
) -> Iterator[BaiduBrowserSession]:
    """启动百度抓取专用的持久 BrowserContext。

    与原 incognito_session 的核心区别：
    - launch_persistent_context 直接返回 BrowserContext（不需要 launch +
      new_context 两步）
    - context.close() 时 cookies / localStorage / indexedDB 落盘到
      user_data_dir，不删
    - 同一时刻只能 1 个 instance 用同一 user_data_dir（OS 层 lock；并发
      限制由 rate_limit.configure_concurrency 保证）

    Args:
        headless: True → 后台跑；False → 弹可见窗口（验证码升级用）。
                  注：patchright stealth fork 不能真正 honor headless=True，
                  所以始终 headed + 推屏外（沿用原 incognito_session 的策略）。
        user_data_dir: 默认 <config_dir>/baidu_browser_profile。

    Yields:
        BaiduBrowserSession，含 .page / .context / .pw 给 adapter 用。

    Raises:
        RuntimeError: patchright 未安装、Chromium 启动失败。
    """
    ensure_browsers_path()
    target_dir = user_data_dir or _default_user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()

        # ── Launch flags ────────────────────────────────────────────────
        # 原 incognito_session 强制 effective_headless=False + 推屏外 +
        # start-minimized 是基于「patchright stealth 不能真 headless」的老
        # 经验。但现代 patchright stealth fork（navigator.webdriver / CDP /
        # UA / WebGL fingerprint patches）跟 headless mode 兼容；老 hack
        # 反而让 OS 把窗口 layout 视为 invalid，所有元素 getBoundingClientRect
        # 返回 0×0，patchright fill / click 内部的 visibility check + scroll-
        # into-view 都触发 "Element is not visible"，30s timeout。
        #
        # 这里直接用 headless=headless 原值。用户传 True → 真 headless（后台
        # 跑、layout 正常 calc）；传 False → headed visible（验证码升级场景）。
        launch_args: list[str] = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1366,768",
            "--blink-settings=imagesEnabled=false",
        ]

        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=headless,
            args=launch_args,
            viewport={"width": 1366, "height": 768},
        )
        # persistent context 通常已有 default page；若是首次冷启 / 没有则新建
        page = context.pages[0] if context.pages else context.new_page()

        # 健康度日志 —— 失败不阻塞 fetch（Section E）
        _log_profile_health(context, target_dir)

        yield BaiduBrowserSession(page=page, context=context, pw=pw)
    finally:
        # LIFO 关闭。context.close() 时 cookies 自动落盘 user_data_dir。
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("baidu context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("baidu pw.stop raised: %s", e)


def _default_user_data_dir() -> Path:
    """<config_dir>/baidu_browser_profile —— 跟 monitor.db 同目录。"""
    from csm_sidecar.services import config_service
    return config_service.get_path().parent / "baidu_browser_profile"


def reset_profile(user_data_dir: Path | None = None) -> None:
    """删整个 profile 目录。下次 baidu_browser_session 启动会冷建。

    给「重置按钮」用（routes/monitor.py 路由调用）。caller 负责确认无 active
    baidu task —— 否则会破坏正在运行的 profile 写入。
    """
    target = user_data_dir or _default_user_data_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("baidu profile reset: %s", target)


def _log_profile_health(context: Any, user_data_dir: Path) -> None:
    """启动后打 1 行 log 标记 profile 状态。fail-soft：任何异常吞掉，
    profile health 日志失败不能阻塞 fetch。

    示例输出：
        baidu profile health: fresh=False, cookies=12, has_BAIDUID=True, path=C:/.../baidu_browser_profile
    """
    try:
        cookies = context.cookies("https://www.baidu.com/")
        has_baiduid = any(c.get("name") == "BAIDUID" for c in cookies)
        # patchright 第一次启动后会建 Default 子目录写 cookie；不存在 = fresh
        is_fresh = not (user_data_dir / "Default").exists()
        logger.info(
            "baidu profile health: fresh=%s, cookies=%d, has_BAIDUID=%s, path=%s",
            is_fresh, len(cookies), has_baiduid, user_data_dir,
        )
    except Exception as e:
        logger.debug("profile health log failed (non-fatal): %s", e)
