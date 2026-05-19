"""百度账号登录态管理：登录 webview / 状态读取 / SERP 后置兜底。

跟 baidu_browser.py 配套：baidu_browser_session 提供 persistent context
contextmanager；本模块提供登录态的写入（open_login_window）+ 读取
（get_login_status）+ 运行时兜底（detect_login_required）。

profile lock：open_login_window 跟 baidu_keyword task 抢同一个
user_data_dir。caller 在 sidecar route 里先 has_active_baidu_task 409 拦截。
"""
from __future__ import annotations

import logging
from typing import Any


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
