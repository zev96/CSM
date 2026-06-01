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
from .chrome_detect import prune_profile_caches

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
    *,
    headless: bool,
    user_data_dir: Path | None = None,
    use_native_chrome: bool = False,
    chrome_executable_path: str | None = None,
    chrome_profile_name: str = "Default",
) -> Iterator[BaiduBrowserSession]:
    """启动百度抓取专用的持久 BrowserContext。

    两种模式：
    - **自建 profile**（默认，向后兼容）：用 CSM 自有 user_data_dir + Patchright 自带
      Chromium。可真 headless。
    - **native Chrome**（``use_native_chrome=True``）：用 channel="chrome" +
      用户的 Chrome.exe + 用户日常 user_data_dir。``headless`` 入参被忽略
      （Chrome stable 不支持 headless persistent context，会启动失败）。

    Args:
        headless: 自建模式下生效；native 模式被强制覆盖为 False。
        user_data_dir: 自建模式 → 默认 ``<config_dir>/baidu_browser_profile``；
                       native 模式 → 必须是用户 Chrome User Data 目录绝对路径。
        use_native_chrome: True = 走 native 分支。
        chrome_executable_path: native 模式必填，用户 Chrome.exe 绝对路径。
        chrome_profile_name: native 模式选哪个 profile（"Default" / "Profile 1"...）。

    Yields:
        BaiduBrowserSession。

    Raises:
        RuntimeError: patchright 未安装、Chromium / Chrome 启动失败。
        ValueError: native 模式但缺 user_data_dir / chrome_executable_path。
    """
    ensure_browsers_path()

    if use_native_chrome:
        if user_data_dir is None:
            raise ValueError("native mode requires user_data_dir")
        if not chrome_executable_path:
            raise ValueError("native mode requires chrome_executable_path")
        target_dir = Path(user_data_dir)
        if headless:
            logger.debug("native mode 忽略 headless=True（Chrome stable 不支持）")
        launch_kwargs: dict[str, Any] = dict(
            user_data_dir=str(target_dir),
            headless=False,
            executable_path=chrome_executable_path,
            channel="chrome",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--profile-directory={chrome_profile_name}",
            ],
            viewport={"width": 1366, "height": 768},
        )
    else:
        target_dir = user_data_dir or _default_user_data_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs = dict(
            user_data_dir=str(target_dir),
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
                "--blink-settings=imagesEnabled=false",
            ],
            viewport={"width": 1366, "height": 768},
        )

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()
        # 自建 profile：headless 用完整 Chromium，避免 chrome-headless-shell 缺失。
        if not use_native_chrome:
            launch_kwargs["executable_path"] = pw.chromium.executable_path
        context = pw.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        _log_profile_health(context, target_dir)
        yield BaiduBrowserSession(page=page, context=context, pw=pw)
    finally:
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
        # native 副本模式：Chrome 已完全关闭（无文件锁），清理本轮攒下的缓存，
        # 使副本常态维持 ~0.5GB。best-effort，失败只 log 不影响已完成的 fetch。
        if use_native_chrome:
            try:
                meta = prune_profile_caches(str(target_dir))
                logger.info(
                    "[baidu native] pruned profile caches: freed %s MB in %ss",
                    meta["freed_mb"], meta["elapsed_s"],
                )
            except Exception as e:
                logger.debug("baidu prune_profile_caches raised: %s", e)


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
