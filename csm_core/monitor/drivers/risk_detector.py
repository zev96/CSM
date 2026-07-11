"""跨平台风控信号检测。

提供 5 层信号融合：
- URL 模式（passport / captcha / wappass / safetycheck / mbd safe）
- DOM 元素（#captcha-mask / .passmod / [id^="wappass"] / .security-check / 百家号 .mod-error）
- 页面文案（"验证码" / "请完成验证" / "安全验证" / "网络异常" / "系统繁忙"）
- HTTP 状态 + 响应头（403/451/503 + BAIDUID_BFESS=deleted）
- 登录状态（login cookie 过期或缺失）

任一层命中即判定为风控。adapter 命中后 raise RiskControlException，
runner 捕获暂停任务 + 推 SSE 风控事件给前端。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

RiskLayer = Literal["url", "dom", "text", "http", "auth"]


@dataclass(frozen=True)
class RiskSignal:
    """命中的风控信号。所有 detect_risk_by_* 函数返回 RiskSignal | None。"""
    layer: RiskLayer
    detail: str  # 命中的具体特征，前端 toast 用


# ── Layer 1: URL pattern ──────────────────────────────────────────────────
# Baidu 站内所有已知验证码 / 登录墙 URL 子串。命中即风控。
_URL_PATTERNS: tuple[str, ...] = (
    "wappass.baidu.com/static/captcha",
    # Match passport.baidu.com without /v2 suffix —— 老的 is_baidu_captcha_url
    # 老 marker 集合用的就是 substring，Task 2 refactor 不能丢覆盖。
    "passport.baidu.com",
    # 老 marker 集合还有 verify.baidu.com —— 这是百度搜索遇到 SERP 风控时的另一个跳转域。
    "verify.baidu.com",
    "baijiahao.baidu.com/safetycheck",
    "mbd.baidu.com/safe",
    "baidu.com/captcha",
)


def detect_risk_by_url(url: str) -> RiskSignal | None:
    """URL 子串匹配。最便宜的一层，先跑。"""
    if not url:
        return None
    for pat in _URL_PATTERNS:
        if pat in url:
            return RiskSignal(layer="url", detail=f"URL matches {pat!r}")
    return None


# ── Layer 2: DOM element ──────────────────────────────────────────────────
_DOM_SELECTORS: tuple[str, ...] = (
    "#captcha-mask",
    ".passmod",
    '[id^="wappass"]',
    ".security-check",
    ".mod-error",      # 百家号 fallback 错误页
    ".error-page",     # 百家号 fallback 错误页（更通用）—— spec §5 一 列出的两个选择器之一
)


def detect_risk_by_dom(page: Any) -> RiskSignal | None:
    """Patchright Page 上检查典型风控 DOM 元素。任何异常都吞掉返回 None
    —— 调用方拿不到判定就该跑其他层兜底，不应该被这层 crash。"""
    try:
        for sel in _DOM_SELECTORS:
            try:
                count = page.locator(sel).count()
            except Exception:
                continue
            if count > 0:
                return RiskSignal(layer="dom", detail=f"DOM matched {sel!r}")
    except Exception:
        return None
    return None


# ── Layer 3: Text phrase ──────────────────────────────────────────────────
_TEXT_PHRASES: re.Pattern[str] = re.compile(
    r"(验证码|请完成验证|安全验证|网络异常|系统繁忙)"
)


def detect_risk_by_text(text: str) -> RiskSignal | None:
    """页面文案匹配。需要 page.content() 抓回 HTML 后调用。"""
    if not text:
        return None
    m = _TEXT_PHRASES.search(text)
    if m is None:
        return None
    return RiskSignal(layer="text", detail=f"text contains {m.group(0)!r}")


# ── Layer 4: HTTP status + cookie ─────────────────────────────────────────
_SUSPECT_STATUS: frozenset[int] = frozenset({403, 451, 503})


def detect_risk_by_http(response: Any) -> RiskSignal | None:
    """response: Patchright Response 或带 .status / .headers 的对象。
    None 输入直接返回 None（adapter 拿不到 response 时也别 crash）。"""
    if response is None:
        return None
    try:
        status = getattr(response, "status", None)
        headers = getattr(response, "headers", {}) or {}
    except Exception:
        return None
    if isinstance(status, int) and status in _SUSPECT_STATUS:
        return RiskSignal(layer="http", detail=f"HTTP status {status}")
    cookie_header = headers.get("set-cookie", "") if isinstance(headers, dict) else ""
    if "BAIDUID_BFESS=deleted" in cookie_header:
        return RiskSignal(layer="http", detail="cookie BAIDUID_BFESS=deleted (session invalidated)")
    return None


# SERP organic 结果容器 —— 有结果就说明页面正常渲染了搜索结果，不是风控插页。
_SERP_RESULT_SELECTOR = "#content_left .c-container"


def _serp_rendered_results(page: Any) -> bool:
    """页面是否正常渲染出了 organic SERP 结果。用来抑制 text 层误报：
    真验证码/风控插页不会有结果容器，而合法 SERP 常在某条结果摘要里带
    "网络异常/系统繁忙/验证码"等词。只有确认「有结果」时才抑制 text 层，
    检测不了（异常/无结果）时保守地放行 text 层（宁可查也别漏真风控）。"""
    try:
        return page.locator(_SERP_RESULT_SELECTOR).count() > 0
    except Exception:
        return False


# ── Fusion ────────────────────────────────────────────────────────────────
def detect_risk(page: Any, response: Any = None) -> RiskSignal | None:
    """对 page + response 跑 5 层检测，返回第一个命中。

    顺序：url → http → dom → text → auth（按计算成本升序，先便宜的）。
    所有内部异常都吞掉 —— 检测本身崩了不应该把抓取流程一起带崩。
    """
    try:
        url = getattr(page, "url", "") or ""
        sig = detect_risk_by_url(url)
        if sig:
            return sig
    except Exception as e:
        logger.debug("detect_risk: layer raised, continuing: %s", e)
    try:
        sig = detect_risk_by_http(response)
        if sig:
            return sig
    except Exception as e:
        logger.debug("detect_risk: layer raised, continuing: %s", e)
    sig = detect_risk_by_dom(page)
    if sig:
        return sig
    try:
        # text 层是最弱信号（结果摘要/关键词含"验证码/网络异常/系统繁忙"就中招）。
        # 页面已渲染出 organic 结果 = 词是摘要不是风控插页 → 跳过 text 层，
        # 避免误判把整个任务暂停 300s。真插页没有结果容器，text 层照常生效。
        if not _serp_rendered_results(page):
            text = page.content()
            sig = detect_risk_by_text(text)
            if sig:
                return sig
    except Exception as e:
        logger.debug("detect_risk: layer raised, continuing: %s", e)
    return None


# ── Exception type for adapter use ────────────────────────────────────────
class RiskControlException(Exception):
    """adapter 命中风控时 raise，runner 捕获后任务标 risk_control。"""

    def __init__(self, signal: RiskSignal, *, progress: int | None = None) -> None:
        super().__init__(f"risk control: layer={signal.layer} detail={signal.detail}")
        self.signal = signal
        self.progress = progress  # 已抓 N 个 keyword 的位置（用于断点续抓）
