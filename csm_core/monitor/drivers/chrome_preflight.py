"""跑 baidu_keyword native mode 前的 Chrome 进程状态预检。

策略：detect → 发通知 → 轮询等关闭 → 关掉后立刻返回 / 超时 raise。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterable

import psutil

logger = logging.getLogger(__name__)


class ChromeStillRunningError(RuntimeError):
    """等待 Chrome 关闭超时。"""


def is_chrome_running() -> bool:
    """检测系统是否有 chrome.exe 进程在跑。

    psutil 偶尔在子进程切换时抛 NoSuchProcess / AccessDenied，吞掉继续遍历。
    """
    for proc in _iter_processes():
        try:
            name = (proc.info.get("name") or "").lower()
            if name == "chrome.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _iter_processes() -> Iterable[psutil.Process]:
    """Indirection 给测试 monkeypatch。"""
    return psutil.process_iter(["name"])


def wait_for_chrome_closed(
    timeout_s: int = 120,
    poll_interval_s: float = 1.0,
    *,
    task_id: int | None = None,
    event_publisher: "Callable[[dict[str, Any]], None] | None" = None,
) -> None:
    """轮询等待 Chrome 关闭。第一次检测到在跑就发通知，关掉立即返回。

    Args:
        timeout_s: 超时秒数。
        poll_interval_s: 轮询间隔。
        task_id: 关联的监控任务 ID（用于 SSE 事件）。None = 不发事件。
        event_publisher: SSE 事件发布回调（DI 模式，避免 csm_core ↔ sidecar 循环
            依赖）。签名：fn({"kind": str, "task_id": int, "remaining_s": int}) -> None。
            None = 不发事件。

    Raises:
        ChromeStillRunningError: 超时仍有 chrome.exe 进程。
    """
    def _maybe_publish(payload: dict[str, Any]) -> None:
        if event_publisher is not None and task_id is not None:
            try:
                event_publisher(payload)
            except Exception:
                logger.exception("event_publisher raised; preflight continues")

    if not is_chrome_running():
        _maybe_publish({"kind": "chrome_closed", "task_id": task_id})
        return

    _notify(
        title="CSM 百度监控",
        body="请关闭 Chrome 浏览器以开始监控（自动检测中）",
    )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        _maybe_publish({
            "kind": "waiting_chrome_close",
            "task_id": task_id,
            "remaining_s": remaining,
        })
        time.sleep(poll_interval_s)
        if not is_chrome_running():
            logger.info("chrome closed, proceeding with native mode")
            _maybe_publish({"kind": "chrome_closed", "task_id": task_id})
            return

    raise ChromeStillRunningError(
        f"等待 Chrome 关闭超时（{timeout_s}s），请手动关闭后重试"
    )


def _notify(*, title: str, body: str) -> None:
    """通知发送 indirection —— 测试可 monkeypatch，prod 由 sidecar 注入。

    本模块不直接依赖 sidecar 通知层，避免 csm_core ↔ sidecar 循环 import。
    sidecar 启动时会调 ``set_notifier(callable)`` 注入真正的实现。
    """
    impl = _notify_impl
    if impl is None:
        logger.warning("notifier not configured; skip: title=%s body=%s", title, body)
        return
    try:
        impl(title=title, body=body)
    except Exception:
        logger.exception("notifier raised; preflight continues")


_notify_impl = None


def set_notifier(fn) -> None:
    """Sidecar lifespan 启动时调用，注入真正的通知发送实现。"""
    global _notify_impl
    _notify_impl = fn
