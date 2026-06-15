"""RPA 浏览器「移屏外 + 运行时上浮」工具。

移屏外（采集时不抢视觉）：offscreen_args() 给 launch_persistent_context 的
args 追加 --window-position 到屏外 + 反遮挡 flags。反遮挡 flags 是关键 ——
否则 Chromium 把屏外窗口当遮挡暂停重绘，元素 boundingClientRect 报 0×0、
fill/click 失效（本仓库之前因此回退过纯 --window-position 方案）。

上浮（验证码/登录需人工时）：surface_window() 用 CDP Browser.setWindowBounds
把窗口移回可见区并 bring_to_front；hide_window() 移回屏外。CDP 失败不崩
（多屏/驱动差异时回退为「窗口留在原位」，记 warning）。
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

_OFFSCREEN = "-32000,-32000"
_OCCLUSION_FLAGS = [
    f"--window-position={_OFFSCREEN}",
    "--disable-features=CalculateNativeWinOcclusion",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def offscreen_args(hidden: bool) -> list[str]:
    """hidden=True → 移屏外+反遮挡 flags；False → 空（不改变窗口位置）。"""
    return list(_OCCLUSION_FLAGS) if hidden else []


def _window_id(page: Any) -> tuple[Any, int]:
    cdp = page.context.new_cdp_session(page)
    wid = cdp.send("Browser.getWindowForTarget")["windowId"]
    return cdp, wid


def _center_bounds(screen_w: int, screen_h: int, win_w: int, win_h: int) -> tuple[int, int]:
    """屏幕居中的窗口左上角坐标；窗口比屏大时 clamp 到 0，不出负坐标。"""
    left = max(0, (screen_w - win_w) // 2)
    top = max(0, (screen_h - win_h) // 2)
    return left, top


def surface_window(page: Any) -> None:
    """把窗口移回屏幕中央 + 置前（验证码/登录人工处理用）。CDP 失败不崩。"""
    win_w, win_h = 1100, 800
    try:
        screen = page.evaluate("({w: screen.availWidth, h: screen.availHeight})")
        left, top = _center_bounds(int(screen["w"]), int(screen["h"]), win_w, win_h)
    except Exception:
        left, top = 80, 80  # 取屏幕尺寸失败 → 退回固定左上角
    try:
        cdp, wid = _window_id(page)
        cdp.send("Browser.setWindowBounds", {
            "windowId": wid,
            "bounds": {"left": left, "top": top, "width": win_w, "height": win_h, "windowState": "normal"},
        })
    except Exception:
        logger.warning("surface_window 失败（CDP 不可用）；窗口可能仍在屏外", exc_info=True)
    try:
        page.bring_to_front()
    except Exception:
        pass


def hide_window(page: Any) -> None:
    """把窗口移回屏外。CDP 失败不崩。"""
    try:
        cdp, wid = _window_id(page)
        cdp.send("Browser.setWindowBounds", {
            "windowId": wid, "bounds": {"left": -32000, "top": -32000},
        })
    except Exception:
        logger.warning("hide_window 失败（CDP 不可用）", exc_info=True)
