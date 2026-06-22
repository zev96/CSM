"""百度关键词排名监控 adapter。

策略：
1. 用 patchright incognito 打开 baidu.com/s?wd=keyword（默认 headless）
2. 用 spec 给的 XPath 抓「默认搜索」「最新资讯」两个区块的 h3//a href
3. 解 baidu.com/link?url=... 跳转拿真实 URL
4. 对每条 URL：curl_cffi + readability 抓正文，识别失败 fallback 浏览器
5. 大小写不敏感匹配 target_brand → matches_brand=True

引擎硬绑 patchright（无痕需 BrowserContext API，drission 不支持）。

新数据模型：
- config.search_keywords: list[str]  (多关键词，每个跑一次 SERP)
- config.target_brand: str           (单品牌词)
- A task = N SERPs × 1 brand
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, quote

from lxml import html as lxml_html

from .. import rate_limit
from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask
from ..drivers.baidu_browser import baidu_browser_session
from ..drivers.baidu_login import detect_login_required
from ..drivers.risk_detector import (
    detect_risk,
    detect_risk_by_http,
    detect_risk_by_text,
    detect_risk_by_url,
    RiskControlException,
    RiskSignal,
)
from ...browser_infra.window_util import surface_window, hide_window
logger = logging.getLogger(__name__)


# 用户提供的两条 XPath（spec 第 1 节末尾）。完整 contains/not 链
# 跟用户原文一致，仅去掉首尾空白 —— XPath 引擎对空白不挑，但单行更易读。
_XPATH_DEFAULT = (
    "//div[contains(@class, 'c-container') "
    "and contains(@class, 'result') "
    "and contains(@class, 'xpath-log') "
    "and contains(@class, 'new-pmd') "
    "and not(@tpl='sp_purc_pc') "
    "and not(@tpl='news-realtime') "
    "and not(@tpl='short_video') "
    "and not(.//span[contains(@class, 'cosc-title-slot')])"
    "]//h3/a"
)

_XPATH_NEWS = (
    "//div[contains(@class, 'cos-space')]"
    "/div[contains(@class, 'cos-row')]"
    "//h3//a"
)

# Chrome 子版本 UA 轮换池。curl_cffi 的 impersonate="chrome120" 在
# _get_session 里保持不变（控制 TLS/H2 fingerprint，跨大版本切换会
# 让 TLS 与 UA header 矛盾更可疑），只换 User-Agent header 在 Chrome
# 119-122 之间轮转。
_UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)


def parse_serp(html: str) -> dict[str, Any]:
    """从一段 SERP HTML 抽取两组 (title, href) 链接。

    纯函数：不发请求、不解 redirect、不判断品牌词 —— 只把 DOM 翻成 list。
    """
    if not html or not html.strip():
        return {"default_links": [], "news_links": [], "news_present": False}

    try:
        doc = lxml_html.fromstring(html)
    except Exception as e:
        logger.warning("baidu parse_serp: lxml fromstring raised: %s", e)
        return {"default_links": [], "news_links": [], "news_present": False}

    default_links = _extract_a_tags(doc, _XPATH_DEFAULT)
    news_links = _extract_a_tags(doc, _XPATH_NEWS)
    return {
        "default_links": default_links,
        "news_links": news_links,
        "news_present": bool(news_links),
    }


def _extract_a_tags(doc: Any, xpath: str) -> list[dict[str, str]]:
    """跑一条 XPath 抓所有 <a>，返回 [{title, href}]。"""
    try:
        nodes = doc.xpath(xpath)
    except Exception as e:
        logger.warning("baidu xpath %r raised: %s", xpath, e)
        return []
    out: list[dict[str, str]] = []
    for a in nodes:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        # 标题文本：百度 h3 里通常有 <em> 高亮，textcontent 直接拿到纯文本
        title = (a.text_content() or "").strip()
        out.append({"title": title, "href": href})
    return out


def match_brand(content: str, brands: list[str]) -> str | None:
    """大小写不敏感找首个出现的目标品牌词。

    "首个" 的含义是 brands 列表里的顺序，不是 content 中位置 ——
    用户排品牌词顺序代表优先级（主品牌排前面）。

    Args:
        content: 待检测正文（不限长度，但建议先 readability 提过）
        brands: 目标品牌词列表，至少非空才有意义

    Returns:
        命中的品牌词原文（保留 brands 列表里的大小写），无命中 → None
    """
    if not content or not brands:
        return None
    content_lc = content.lower()
    for brand in brands:
        if brand and brand.lower() in content_lc:
            return brand
    return None


# Indirection 给单测 monkeypatch 用。真实调用走 curl_cffi。
def _cc_get(url: str, *, session: Any = None, **kwargs: Any) -> Any:
    """HTTP GET via curl_cffi.

    ``session=None`` (legacy) → stateless single-request curl_cffi.requests.get
    ``session=<Session>``      → session.get keeping cookie jar / connection pool

    Indirection retained for single-test monkeypatching. Session-mode
    drops any ``impersonate=`` kwarg since the Session was already
    constructed with one.
    """
    if session is not None:
        kwargs.pop("impersonate", None)
        return session.get(url, **kwargs)
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, **kwargs)


def resolve_baidu_link(url: str, *, session: Any = None) -> str:
    """如果是 baidu.com/link?url=... 跳转，跟随 redirect 拿真实 URL。

    非百度跳转 URL 直接返回。任何异常 → 返回原 URL（adapter 自然把它当
    抓取失败 source）。

    ``session`` —— 可选 curl_cffi.Session 复用 cookie / connection pool。
    None 时走 stateless 旧路径（保留给单测 monkeypatch _cc_get 用）。
    """
    if not url or "baidu.com/link?" not in url:
        return url
    try:
        resp = _cc_get(
            url,
            session=session,
            impersonate="chrome120",
            allow_redirects=True,
            timeout=10,
        )
        return getattr(resp, "url", None) or url
    except Exception as e:
        logger.info("resolve_baidu_link(%s) raised: %s", url[:60], e)
        return url


# 决定是否升级浏览器的最短正文阈值。少于这个字数说明 readability
# 没真正提到内容（典型 SPA「请用 APP 打开」壳页），交给浏览器 fallback。
_HTTP_MIN_CONTENT_CHARS = 200


def fetch_article_http(url: str, *, session: Any = None) -> dict[str, Any]:
    """用 curl_cffi + readability 抓单篇文章，返回纯文本正文。

    ``session`` —— 可选 curl_cffi.Session 复用 cookie / connection pool。
    None 时走 stateless 旧路径（保留给单测 monkeypatch _cc_get 用）。

    Returns:
        dict 含:
            content: str — 提取出的正文（失败时为 ""）
            source: "http"
            fetch_error: str | None — 失败原因
            needs_browser_fallback: bool — adapter 据此判断是否升级到浏览器
    """
    try:
        resp = _cc_get(
            url,
            session=session,
            impersonate="chrome120",
            allow_redirects=True,
            timeout=15,
        )
    except Exception as e:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"http request raised: {e!r}",
            "needs_browser_fallback": True,
        }

    if resp.status_code >= 400:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"http {resp.status_code}",
            "needs_browser_fallback": True,
        }

    ctype = (resp.headers.get("content-type") or "").lower()
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"unexpected content-type: {ctype}",
            "needs_browser_fallback": True,
        }

    raw = getattr(resp, "text", "") or ""

    # Article-level 风控检测（与 fetch_article_browser 的 detect_risk 对齐，
    # 但跳过 DOM 层 —— 我们没有 page，只有 raw HTML + Response）。
    #
    # 没这层时百家号的 https://baijiahao.baidu.com/safetycheck 这类验证码页
    # 会返回 200 OK + 一段 HTML：readability 提出来 > 200 字（验证码说明 +
    # 按钮文本），整段被当成"真实文章正文"存进 content_preview，污染下游
    # match_brand 判断（虽然验证码页通常不含品牌词，但 content_preview
    # 本身已是脏数据，用户看不到真实文章内容）。
    #
    # 粒度：article-level fetch_error，不 raise RiskControlException。curl_cffi
    # 是无状态单次请求，单条 URL 触发风控不等于整个 session 被识别（不像
    # browser fallback 共享 cookie）。fetch_error 写"百度风控"让上层标该
    # 条 fetch 失败但继续抓其他文章；needs_browser_fallback=False 因为
    # browser fallback 触发风控会 raise → 整个 task pause，比 article-level
    # fail 影响大得多。
    final_url = getattr(resp, "url", url) or url
    risk = (
        detect_risk_by_url(final_url)
        or detect_risk_by_http(resp)
        or detect_risk_by_text(raw)
    )
    if risk is not None:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"百度风控：layer={risk.layer} {risk.detail}",
            "needs_browser_fallback": False,
        }

    content = _extract_readable_text(raw)
    if len(content) < _HTTP_MIN_CONTENT_CHARS:
        # 方案 A 兜底：SPA / 前端渲染站（如 post.smzdm.com）服务端 HTML
        # 里没有真实文章正文（正文 JS 渲染），readability 主内容算法
        # 提不出来。直接拿整个 <body> text_content ── meta / 标题 /
        # nav / 偶尔在 HTML 里残留的 brand 字符串都能被 match_brand 看到。
        raw_text = _extract_raw_body_text(raw)
        if len(raw_text) > len(content):
            return {
                "content": raw_text,
                "source": "http_raw_fallback",
                "fetch_error": (
                    f"readable too short ({len(content)} chars), "
                    f"fallback to raw body text ({len(raw_text)} chars)"
                ),
                "needs_browser_fallback": False,
            }
        # 方案 C 兜底：JS challenge 反爬站（smzdm 等）── 第一次 HTTP 拿到的
        # 只是 < 500 字符的 JS 探针壳页（probe.js fingerprint check），body
        # 完全是空的，连 raw_text 也拿不出来。这种 case 让 caller 用 SERP
        # title 兜底匹配 brand（标题党概率低于反爬概率，且明确 mark 了
        # is_js_challenge 让 caller 知道是反爬触发的 fallback）。
        if len(raw) < 500:
            return {
                "content": "",
                "source": "http_js_challenge_no_body",
                "fetch_error": f"JS challenge shell ({len(raw)} chars HTML), use SERP title fallback",
                "needs_browser_fallback": False,
                "is_js_challenge": True,
            }
        return {
            "content": content,
            "source": "http",
            "fetch_error": f"readable content too short ({len(content)} chars)",
            "needs_browser_fallback": True,
        }

    return {
        "content": content,
        "source": "http",
        "fetch_error": None,
        "needs_browser_fallback": False,
    }


def _extract_raw_body_text(raw_html: str) -> str:
    """lxml fallback ── 不走 readability 主内容识别，直接拿 <body> text。

    用于 SPA / 前端渲染站（smzdm 等）── readability 找不到主内容但 HTML
    里仍有 brand 字符串（meta、og:title、nav 链接、JSON-LD 等）的场景。
    准确度低于 readability，但比 content_len=0 漏检强。

    script / style tag 被 lxml 的 text_content() 自动 strip 在文本之外，
    所以不会拿到 JS 代码 noise。但 SPA 的 inline JSON state（写在 <script
    type="application/json"> 里）会被 strip ── 那部分需要更专门的 SPA
    解析器（方案 C），本 fallback 不 cover。
    """
    if not raw_html.strip():
        return ""
    try:
        doc = lxml_html.fromstring(raw_html)
    except Exception as e:
        logger.info("raw body text extraction failed: %s", e)
        return ""
    body = doc.find(".//body") if doc is not None else None
    target = body if body is not None else doc
    try:
        return (target.text_content() or "").strip()
    except Exception:
        return ""


def _extract_readable_text(raw_html: str) -> str:
    """readability-lxml 提正文。失败返回空串。"""
    if not raw_html.strip():
        return ""
    try:
        from readability import Document
    except ImportError:
        logger.warning("readability-lxml not installed; falling back to lxml text_content")
        try:
            doc = lxml_html.fromstring(raw_html)
            return (doc.text_content() or "").strip()
        except Exception:
            return ""
    try:
        doc = Document(raw_html)
        summary_html = doc.summary(html_partial=True)
        text = lxml_html.fromstring(summary_html).text_content() if summary_html else ""
        return (text or "").strip()
    except Exception as e:
        logger.info("readability summary raised: %s", e)
        return ""


def fetch_article_browser(page: Any, url: str) -> dict[str, Any]:
    """浏览器 fallback：用已有的 patchright Page 打开 URL，读 HTML 提正文。

    跟 HTTP-first 函数返回结构一致，方便上游统一处理。

    复用同一个 incognito context 的 Page —— SERP 抓完后，循环里
    每条 URL 在同 page 上 goto 切走（不开新 tab，避免句柄爆炸）。

    Raises:
        RiskControlException: page.goto 落到 wappass / verify.baidu / safetycheck
            等风控页时抛出（detect_risk 4 层任一命中）。progress=None 表示文章页
            风控不绑定具体 keyword 进度 —— 整个会话被识别，跟 SERP 命中走同一条
            retry/breakpoint 路径，runner 端 ``(e.progress or 0)`` 自然 fallback 到 0。
    """
    response = None
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except TypeError:
        # FakePage 不接受关键字参数：测试场景
        try:
            response = page.goto(url)
        except Exception as e:
            return {
                "content": "",
                "source": "browser",
                "fetch_error": f"page.goto raised: {e!r}",
                "needs_browser_fallback": False,
            }
    except Exception as e:
        return {
            "content": "",
            "source": "browser",
            "fetch_error": f"page.goto raised: {e!r}",
            "needs_browser_fallback": False,
        }

    # 文章页 4 层风控融合检测（URL + HTTP + DOM + text）。任一层命中 →
    # 抛 RiskControlException，让 runner 跟 SERP 命中走同一条 retry/breakpoint
    # 路径。progress=None 表示非 per-keyword 风控（不是某 keyword 卡住，是会话级）。
    risk = detect_risk(page, response)
    if risk is not None:
        raise RiskControlException(risk, progress=None)

    try:
        raw = page.content() or ""
    except Exception as e:
        return {
            "content": "",
            "source": "browser",
            "fetch_error": f"page.content raised: {e!r}",
            "needs_browser_fallback": False,
        }

    text = _extract_readable_text(raw)
    return {
        "content": text,
        "source": "browser",
        "fetch_error": None if text else "browser content empty after readability",
        "needs_browser_fallback": False,
    }


def _is_captcha_page(raw: str, url: str) -> bool:
    """检测一段 rendered HTML + URL 是不是验证码 / 反爬页。

    detect_risk_by_* 是百度专用 pattern，这里再补一组跨站通用的验证码
    关键词（smzdm / 知乎 / 其他站）。
    """
    # 正文 body text 已经够长 → 不是验证码页（即使 <head> 残留 captcha SDK
    # 的 script 引用含 "captcha" 字样也不误判）。验证码页 body 很短（验证 UI
    # 文字少），正文页 body 几 KB。这条短路避免"进了正文还被判验证码"卡死。
    if len(_extract_raw_body_text(raw)) >= 800:
        return False
    if detect_risk_by_text(raw) or detect_risk_by_url(url):
        return True
    head = raw[:5000]
    return any(
        kw in head
        for kw in (
            "人机验证", "滑动验证", "请完成安全验证", "拖动滑块",
            "captcha", "verify you are human", "security check",
        )
    )


def fetch_article_browser_isolated(
    context: Any,
    url: str,
    *,
    timeout_ms: int = 20000,
    spa_wait_ms: int = 3000,
    solve_timeout_s: int = 180,
    solve_poll_s: float = 2.0,
) -> dict[str, Any]:
    """方案 B：用独立 tab 打开文章 URL 让 JS 跑完后提正文。

    跟 ``fetch_article_browser`` 的区别：不用 baidu 主 page，而是
    ``context.new_page()`` 开一个独立 tab，对反爬站（zhihu / smzdm 等
    HTTP 拿不到正文）用真正"点击进文章"的方式拿 rendered HTML。

    **article 级软着陆**（2026-05-28，用户要求）：smzdm 等强反爬站对
    自动化浏览器弹验证码（用户日常 Chrome 不弹，但 Patchright 有自动化
    指纹）。检测到验证码页时**不立即关 tab**，而是弹通知 + 保持 tab 打开
    + 轮询等用户手动解。解完后页面进真正文章 → 拿 rendered HTML 提正文
    match。超时（默认 180s）才放弃。用户明确要"输验证码进页面后筛正文"，
    而不是退到 SERP title。

    Returns 跟 fetch_article_http 同 shape，额外 is_blocked 字段。
    """
    new_page = None
    try:
        try:
            new_page = context.new_page()
        except Exception as e:
            return {
                "content": "",
                "source": "browser_isolated",
                "fetch_error": f"new_page raised: {e!r}",
                "needs_browser_fallback": False,
            }
        try:
            new_page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            return {
                "content": "",
                "source": "browser_isolated",
                "fetch_error": f"new_page.goto raised: {e!r}",
                "needs_browser_fallback": False,
            }
        # SPA 站 domcontentloaded 后正文还没渲染 ── 给 N 毫秒让 JS 跑完
        try:
            new_page.wait_for_timeout(spa_wait_ms)
        except Exception:
            pass
        try:
            raw = new_page.content() or ""
            cur_url = new_page.url or ""
        except Exception as e:
            return {
                "content": "",
                "source": "browser_isolated",
                "fetch_error": f"new_page.content raised: {e!r}",
                "needs_browser_fallback": False,
            }

        # article 级软着陆：检测到验证码页 → 弹通知 + 等用户手动解
        if _is_captcha_page(raw, cur_url):
            _notify(
                title="CSM 文章验证",
                body=f"文章页需要验证（{cur_url[:50]}），请在弹出的浏览器标签页完成验证后等待自动继续",
            )
            logger.info("[baidu] article captcha, waiting for human solve: %s", url[:80])
            deadline = time.monotonic() + solve_timeout_s
            solved = False
            while time.monotonic() < deadline:
                try:
                    new_page.wait_for_timeout(int(solve_poll_s * 1000))
                except Exception:
                    break
                try:
                    raw = new_page.content() or ""
                    cur_url = new_page.url or ""
                except Exception:
                    break
                # 解完判定：用"正文是否出现"（body text 够长）而不是"验证码
                # 关键词消失"。smzdm 正文页 <head> 残留 captcha SDK 的
                # script 引用（probe.js 等含 "captcha" 字样），靠关键词消失
                # 会误判"还在验证码页"卡到超时。验证码页 body text 很短
                # (< 300)，正文页很长 (> 800) ── 用长度区分稳得多。
                if len(_extract_raw_body_text(raw)) >= 800:
                    solved = True
                    logger.info("[baidu] article captcha solved, resuming: %s", url[:80])
                    # 解完后页面可能刚跳转，再等一下让正文渲染
                    try:
                        new_page.wait_for_timeout(spa_wait_ms)
                        raw = new_page.content() or ""
                    except Exception:
                        pass
                    break
            if not solved:
                logger.warning("[baidu] article captcha solve timeout: %s", url[:80])
                return {
                    "content": "",
                    "source": "browser_isolated",
                    "fetch_error": f"验证码解题超时（{solve_timeout_s}s）",
                    "needs_browser_fallback": False,
                    "is_blocked": True,
                }

        # readability 提正文，失败 fallback raw body text
        text = _extract_readable_text(raw)
        if len(text) < _HTTP_MIN_CONTENT_CHARS:
            text = _extract_raw_body_text(raw)
        return {
            "content": text,
            "source": "browser_isolated",
            "fetch_error": None if text else f"browser_isolated empty (raw={len(raw)} chars)",
            "needs_browser_fallback": False,
            "is_blocked": False,
        }
    finally:
        if new_page is not None:
            try:
                new_page.close()
            except Exception:
                pass


# ── 软着陆验证码 ────────────────────────────────────────────────
# 复用 risk_detector 的同一组 pattern，避免两边 drift（detect_risk 看到的就是
# _try_human_solve 等的，反之亦然）。
from ..drivers.risk_detector import _URL_PATTERNS as _RISK_URL_PATTERNS
from ..drivers.risk_detector import _DOM_SELECTORS as _RISK_DOM_SELECTORS
_notify_impl: Any = None


def _notify(*, title: str, body: str) -> None:
    """通知发送 indirection —— sidecar 注入实现。csm_core 不直接依赖 sidecar。"""
    if _notify_impl is None:
        logger.warning("notifier not configured; skip: title=%s body=%s", title, body)
        return
    try:
        _notify_impl(title=title, body=body)
    except Exception:
        logger.exception("notifier raised; continue")


def set_notifier(fn: Any) -> None:
    """Sidecar 启动时注入。"""
    global _notify_impl
    _notify_impl = fn


def _try_human_solve(
    *,
    page: Any,
    keyword: str,
    kw_idx: int,
    timeout_s: int = 300,
    poll_interval_s: float = 1.0,
    task_id: int | None = None,
    event_publisher: Any = None,
) -> bool:
    """命中风控时弹通知 + 轮询等用户解题。

    Args:
        page, keyword, kw_idx: 当前 SERP 上下文。
        timeout_s, poll_interval_s: 超时和轮询。
        task_id: 关联监控任务 ID（用于 SSE）。
        event_publisher: 同 chrome_preflight，DI 注入。
            签名：fn({"kind": str, "task_id": int, "keyword": str, "kw_idx": int}) -> None。

    Returns:
        True  — 用户解完，URL 离开风控域名 + DOM 验证码元素消失。caller retry 当前 kw。
        False — 超时仍在风控页。caller 走原 raise RiskControlException 路径。
    """
    _notify(
        title="CSM 百度监控",
        body=f"需要人工解验证码（关键词：{keyword}），点击浏览器窗口完成",
    )
    if event_publisher is not None and task_id is not None:
        try:
            event_publisher({
                "kind": "needs_captcha",
                "task_id": task_id,
                "keyword": keyword,
                "kw_idx": kw_idx,
            })
        except Exception:
            logger.exception("event_publisher raised; continue")

    # 把窗口移到屏幕可见区，方便用户找到并操作验证码
    surface_window(page)

    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            time.sleep(poll_interval_s)
            try:
                cur_url = page.url or ""
            except Exception:
                cur_url = ""
            in_risk = any(p in cur_url for p in _RISK_URL_PATTERNS)
            if in_risk:
                continue
            # URL 已离开风控域名 → 再检 DOM 验证码元素是否消失
            any_captcha_dom = False
            for sel in _RISK_DOM_SELECTORS:
                try:
                    if page.query_selector(sel) is not None:
                        any_captcha_dom = True
                        break
                except Exception:
                    continue
            if not any_captcha_dom:
                logger.info("human solve detected; resuming keyword #%d (%s)", kw_idx, keyword)
                return True

        logger.warning("human solve timeout for keyword #%d (%s)", kw_idx, keyword)
        return False
    finally:
        # 无论解完还是超时，都把窗口移回屏外
        hide_window(page)


def _navigate_to_serp(page: Any, keyword: str) -> Any:
    """直接 goto SERP url。返回 navigation response 给 detect_risk 用。

    回归原架构 —— 三段式 home/fill/Enter 的时间 pattern 反而是 bot 信号。
    带登录态（BDUSS）的直接 goto 看起来像真实用户从书签或外链进 SERP，
    是 baidu organic 流量的主要形态。
    """
    serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
    # timeout 60s ── native mode 副本 Chrome 首次启动 + 加载首个 SERP 慢
    # （包括 OS profile lock 检查、Chrome extension 初始化、Network 服务起
    # 等），实测 30s 不够，第一个 keyword 经常 timeout 失败。
    return page.goto(serp_url, wait_until="domcontentloaded", timeout=60000)


class BaiduKeywordAdapter:
    """`BaseMonitorAdapter` 实现。SERP → 解链 → 抓正文 → 品牌匹配 → MonitorResult。

    新模型：config.search_keywords (list[str]) + config.target_brand (str)。
    每个 keyword 跑一次独立 SERP，结果聚合到 metric.keywords[] + task 级统计。

    引擎硬绑 patchright incognito。风控命中抛 RiskControlException，
    runner（Task 4）决定 retry/pause；in-task auto-promotion 已废弃。
    """

    platform: str = "baidu_keyword"

    # Pacer keys 给 _check_block 用：跟 SERP 间 pacer ("baidu_keyword")
    # 分开，因为 SERP 间隔窗口 5-10s 是为整页跳转设的，对 10 条 article
    # 链接级别太重；article 间需要独立、更短（默认 2-5s）的节奏窗口。
    # 同时单独切出 baijiahao 是因为它是 baidu 自家子域反爬最严的（第三
    # 方软文站秒抓不触发，百家号秒抓必触发），需要比普通 article 更长
    # 的间隔（默认 5-10s 抖动）。
    _ARTICLE_PACER_KEY = "baidu_keyword:article"
    _BAIJIAHAO_PACER_KEY = "baidu_keyword:baijiahao"
    # 用 host endswith 匹配，覆盖 baijiahao.baidu.com / mbd.baidu.com /
    # 偶发的 mp.baidu.com 等百度生态内容站；都共享一个 cookie / 风控池。
    _BAIJIAHAO_HOSTS: tuple[str, ...] = (
        "baijiahao.baidu.com",
        "mbd.baidu.com",
        "mp.baidu.com",
    )

    def __init__(self) -> None:
        # 真实字段在 apply_settings 里被覆盖。
        # 百度恒有头（见 _run 里 effective_headless）—— 这个默认值现已不参与决策，
        # 留作语义标记。
        self._headless_default = False
        self._captcha_timeout_s = 90
        # 默认排除域名（B2B / 电商）。apply_settings 会用 config 里的值
        # 覆盖；空 list 表示「不应用全局黑名单」（用户在设置页清空时）。
        self._default_excluded_domains: tuple[str, ...] = ()
        # UA 轮换游标 + per-task curl_cffi.Session 池。Session 内含 cookie jar，
        # per-task 复用让 BAIDUID / BIDUPSID baseline cookie 不被频繁丢弃 →
        # 大幅降低百度风控触发率（参考 bilibili_comment 同款模式）。
        self._ua_idx = 0
        self._http_sessions: dict[int, Any] = {}
        self._http_sessions_lock = threading.Lock()
        self._event_publisher: Any = None

    def set_event_publisher(self, fn: Any) -> None:
        """Sidecar lifespan 启动时注入，给 native mode chrome_preflight +
        软着陆验证码 发 SSE 事件用。"""
        self._event_publisher = fn

    def _next_ua(self) -> str:
        """Round-robin pick from _UA_POOL. Called only by _get_session
        so each Session gets a stable UA for its lifetime — switching UA
        mid-session would itself be a bot signal."""
        ua = _UA_POOL[self._ua_idx % len(_UA_POOL)]
        self._ua_idx += 1
        return ua

    def _get_session(self, task_id: int) -> Any:
        """Get-or-create curl_cffi.Session for this task. First call warm-ups
        by GET https://www.baidu.com/ to seed BAIDUID/BIDUPSID baseline cookies.

        Thread safety: BAIDU_ADAPTER is a module singleton and the ThreadPool
        in monitor_loop runs multiple tasks concurrently. The lock guards the
        dict only — the Session itself is used single-threaded inside one
        task's _fetch_once → _check_block path, so per-session calls don't
        need synchronization.

        Warm-up failure is non-fatal: subsequent real requests will build
        cookies naturally; warm-up only reduces the "naked cookie" risk on
        the first article fetch.
        """
        with self._http_sessions_lock:
            sess = self._http_sessions.get(task_id)
            if sess is not None:
                return sess
            import importlib
            cc_requests = importlib.import_module("curl_cffi.requests")
            sess = cc_requests.Session(impersonate="chrome120")
            sess.headers.update({
                "User-Agent": self._next_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
            try:
                sess.get("https://www.baidu.com/", timeout=8)
            except Exception as e:
                logger.info("baidu session warmup failed (task=%d): %s", task_id, e)
            self._http_sessions[task_id] = sess
            return sess

    def _drop_session(self, task_id: int) -> None:
        """Drop and close the per-task Session. Called from fetch()'s finally
        block so every task gets a fresh session next time — long-lived
        sessions accumulate request-count signals that baidu uses to flag
        bots. Idempotent: dropping an absent task_id is a no-op."""
        with self._http_sessions_lock:
            sess = self._http_sessions.pop(task_id, None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    def apply_settings(
        self,
        *,
        headless_default: bool = True,
        captcha_visible_timeout_s: int = 90,
        captcha_max_promotions: int = 1,
        serp_pacing_seconds: int = 5,
        article_pacing_seconds: int = 3,
        baijiahao_pacing_seconds: int = 8,
        breaker_failures: int = 3,
        breaker_cooldown_seconds: int = 600,
        default_excluded_domains: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """挂接 settings.monitor.baidu_keyword.*。lifecycle 启动 + 设置页保存时各调一次。

        ``article_pacing_seconds`` —— SERP 解析完 N 条链接后，逐条抓正文之间
        要等多久（min）；max = min * 2 抖动。默认 3-6s。原来这一层没有节流，
        10 条链接秒级连发到 baidu 网域，是百家号触发验证码的主要诱因。

        ``baijiahao_pacing_seconds`` —— 同上但**仅对百家号/mbd/mp 子域生效**，
        独立的 pacer 实例。百家号是 baidu 自家子域反爬最严的（第三方软文站
        高速抓没事），需要比普通 article 更宽的窗口。默认 8-16s。
        """
        from ..rate_limit import get_pacer, get_breaker, configure_concurrency

        self._headless_default = headless_default
        self._captcha_timeout_s = captcha_visible_timeout_s
        # captcha_max_promotions 入参保留以保持向后兼容，但值已无效。
        # Task 3 起 auto-promotion 路径废弃，risk control 由 runner 决定 retry。
        _ = captcha_max_promotions  # noqa: F841 — Ignored since Task 3
        # Normalize to lowercase + stripped tuple (cheap immutable snapshot
        # so the fetch path doesn't need a lock if settings re-applies
        # mid-flight).
        if default_excluded_domains is None:
            default_excluded_domains = ()
        self._default_excluded_domains = tuple(
            d.strip().lower() for d in default_excluded_domains if d and d.strip()
        )

        pacer = get_pacer(self.platform)
        # 把 spec 的 serp_pacing_seconds 映射成 pacer 的 (min, max) jitter 窗口。
        pacer.configure(
            delay_min=float(serp_pacing_seconds),
            delay_max=float(serp_pacing_seconds * 2),
        )
        # Article-level pacers —— 跟 SERP 间 pacer ("baidu_keyword") 完全独立的
        # 单例实例，by name 区分。jitter 窗口 (min, max*2) 复用 serp 同款映射，
        # 让"配 5s 实际 5-10s 抖"的直觉跟用户原有的 serp_pacing_seconds 一致。
        get_pacer(self._ARTICLE_PACER_KEY).configure(
            delay_min=float(article_pacing_seconds),
            delay_max=float(article_pacing_seconds * 2),
        )
        get_pacer(self._BAIJIAHAO_PACER_KEY).configure(
            delay_min=float(baijiahao_pacing_seconds),
            delay_max=float(baijiahao_pacing_seconds * 2),
        )
        breaker = get_breaker(self.platform)
        breaker.failure_threshold = breaker_failures
        breaker.cool_off_seconds = float(breaker_cooldown_seconds)
        # persistent_context profile lock requires exclusive user_data_dir
        # access — force baidu task serial execution. configure_concurrency
        # is idempotent (replaces the semaphore object); calling on every
        # apply_settings is safe.
        configure_concurrency(self.platform, 1)

    # ── exclude-domain helpers ──────────────────────────────────────
    def _build_exclude_set(self, task: MonitorTask) -> set[str]:
        """Merge global default + per-task ``exclude_domains`` into a
        single lowercase set of patterns. Task can opt out of the global
        list by setting ``use_default_excludes: false``.
        """
        out: set[str] = set()
        cfg = task.config or {}
        if cfg.get("use_default_excludes", True):
            out.update(self._default_excluded_domains)
        for d in (cfg.get("exclude_domains") or []):
            if isinstance(d, str):
                d2 = d.strip().lower()
                if d2:
                    out.add(d2)
        return out

    @staticmethod
    def _is_host_excluded(host: str, exclude_set: set[str]) -> bool:
        """Match host against any pattern. host equals pattern OR ends
        with ('.' + pattern) — covers subdomains like ``mall.jd.com``.
        """
        if not host or not exclude_set:
            return False
        h = host.lower()
        for pat in exclude_set:
            if h == pat or h.endswith("." + pat):
                return True
        return False

    def fetch(
        self,
        task: MonitorTask,
        *,
        progress_cb: "Callable[[int, int], None] | None" = None,
        cancel_token: Any = None,
        resume_from: int = 0,
    ) -> MonitorResult:
        """Run one round of SERP scraping for all configured keywords.

        ``progress_cb(current, total)`` is called after each keyword
        completes so the UI can render a "N / M" progress bar live.
        ``current`` starts at 1 (after first keyword done) and ends at
        ``total``; the loop publishes (0, total) once up front so the bar
        shows the total count immediately on start.

        ``cancel_token`` is a duck-typed object exposing ``is_set() -> bool``
        (we accept ``threading.Event`` from the sidecar; ``None`` skips
        cancellation entirely so unit tests don't need to fake it).

        ``resume_from`` — 0-based index of the first keyword to scrape.

        Session lifecycle: a per-task curl_cffi.Session is created up-front
        (warm-up GET baidu.com seeds BAIDUID baseline cookies), threaded
        through _fetch_with_promotion → _fetch_once → _check_block →
        fetch_article_http / resolve_baidu_link, and ALWAYS dropped in
        finally — both on normal completion (don't accumulate request-count
        signal that bots get flagged for) and on RiskControlException
        (dirty cookies that already triggered captcha must not be reused).
        ``_drop_session`` is idempotent (uses dict.pop with default).
        """
        breaker = rate_limit.get_breaker(self.platform)
        if not breaker.allow():
            cooldown_min = max(1, int(breaker.cool_off_seconds / 60))
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                # 'failed' 而非 'risk_control'：这不是百度反爬断点（根本没抓），是
                # 本地连续失败触发的熔断保护。用 risk_control 会被前端当成「未跑 +
                # keyword #0 断点」误导用户、还经由 monitor_loop 发出「监测任务完成」
                # 假通知；failed 让前端正确显示「失败」+ 下面的中文原因。
                status="failed",
                rank=-1,
                error_message=(
                    f"百度反爬熔断中：因连续抓取失败已临时暂停，约 {cooldown_min} 分钟后"
                    "自动恢复（或重启应用立即清除）。常见根因：副本 Chrome 启动失败 / "
                    "副本登录态(BDUSS)失效 —— 请到设置页「重新导入」并「登录百度（副本）」。"
                ),
            )

        # ── Fast-fail: validate keyword/brand BEFORE preflight ───────────
        # 移到 preflight 之前：config 错的任务不要等 120s Chrome 关闭再失败。
        cfg = task.config or {}
        keywords_raw = cfg.get("search_keywords") or []
        keywords = [k.strip() for k in keywords_raw if k and k.strip()]
        brand = (cfg.get("target_brand") or "").strip()
        # 品牌别名：同品牌多叫法（如 CEWEY / 希喂），任一命中即自家。
        # match_brand 已支持多词 OR；喂 [brand, *aliases]。缺省=空=退化单 brand。
        aliases = [a.strip() for a in (cfg.get("brand_aliases") or []) if a and a.strip()]

        if not keywords or not brand:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="config.search_keywords (non-empty list) + target_brand required",
            )

        # ── Native mode config ────────────────────────────────────
        # B' pivot (2026-05-25): 不再调 chrome_preflight ── 副本路径独立 OS lock，
        # 跟用户日常 Chrome 可以共存。
        #
        # lazy import 避免 csm_core → csm_sidecar 循环；用 config_service.load()
        # 而非 csm_config.get_config() 是为了拿测试 fixture (sidecar/tests/conftest.py
        # settings_path) 注入的 config，而不是真实 user disk 上的 settings.json。
        from csm_sidecar.services import config_service as _cfg_svc
        app_cfg = _cfg_svc.load()
        baidu_cfg = app_cfg.monitor.baidu_keyword
        use_native = bool(baidu_cfg.use_native_chrome)

        # native 模式必须先导入副本（chrome_profile_copy_path）
        if use_native and not baidu_cfg.chrome_profile_copy_path:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="error",
                rank=-1,
                error_message="native mode 启用但未导入 Chrome profile 副本，请到设置页点'复制 Chrome profile'",
            )
        # native mode 还要 executable
        if use_native and not baidu_cfg.chrome_executable_path:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="error",
                rank=-1,
                error_message="native mode 启用但缺 Chrome 可执行文件路径，请到设置页配置",
            )

        session_kwargs: dict[str, Any] = {}
        if use_native:
            session_kwargs.update(
                use_native_chrome=True,
                user_data_dir=Path(baidu_cfg.chrome_profile_copy_path),
                chrome_executable_path=baidu_cfg.chrome_executable_path,
                chrome_profile_name="Default",  # 副本内固定叫 Default
            )
        # native 强制 headless=False（baidu_browser_session 内部也会忽略）
        # ─────────────────────────────────────────────────────────

        # 百度恒有头 + 屏外：验证码必须可见可操作（无头无窗口 surface_window 无效）。
        # 屏外参数 offscreen_args 在有头时自动生效，平时窗口停在 -32000 不打扰；有头
        # 真窗口反爬指纹也更干净，可能降低验证码触发。native 模式本就强制有头。
        effective_headless = False
        rate_limit.get_pacer(self.platform).wait()

        # Clamp resume_from to valid range so callers don't need to guard.
        resume_from = max(0, min(int(resume_from), len(keywords)))

        session = self._get_session(task.id or 0)
        try:
            return self._fetch_with_promotion(
                task, keywords, brand, effective_headless, progress_cb, cancel_token,
                resume_from=resume_from,
                session=session,
                session_kwargs=session_kwargs,
            )
        finally:
            # Drop on every exit path (normal return / RiskControlException /
            # any other adapter exception). Idempotent so even if something
            # downstream already called _drop_session, this is safe.
            self._drop_session(task.id or 0)

    def _fetch_with_promotion(
        self,
        task: MonitorTask,
        keywords: list[str],
        brand: str,
        headless: bool,
        progress_cb: "Callable[[int, int], None] | None" = None,
        cancel_token: Any = None,
        *,
        resume_from: int = 0,
        session: Any = None,
        session_kwargs: "dict[str, Any] | None" = None,
    ) -> MonitorResult:
        """跑一次所有 SERP。命中 RiskControlException 直接传给 runner，
        runner（Task 4）决定 retry 还是 pause + 写断点。此函数不再做 in-task
        auto-promotion —— 老的 headless→可见浏览器自动升级路径已废弃。
        """
        breaker = rate_limit.get_breaker(self.platform)
        try:
            result = self._fetch_once(
                task, keywords, brand, headless, progress_cb, cancel_token,
                resume_from=resume_from,
                session=session,
                session_kwargs=session_kwargs,
            )
        except RiskControlException:
            # 4 层风控命中 —— 让 runner (Task 4) 捕获写断点 + 暂停任务；不计入熔断器。
            raise
        except Exception as e:
            logger.exception("baidu fetch raised: %s", e)
            breaker.record_failure()
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message=f"adapter exception: {e!r}",
            )

        if result.status == "ok":
            breaker.record_success()
        else:
            breaker.record_failure()
        return result

    def _assert_baidu_logged_in(self, cookies: list[dict[str, Any]], *, resume_from: int) -> None:
        """Raise RiskControlException(layer='auth') if BDUSS is missing.

        Caller passes the cookies it already read on the live persistent
        context. Keeping this a pure function makes it cheap to unit test.

        ``progress=resume_from`` so the runner's breakpoint bookkeeping
        (already_fetched + 1 == next-to-resume) stays consistent —
        nothing was fetched in this run; resume from the same index.
        """
        has_bduss = any(c.get("name") == "BDUSS" for c in cookies)
        if not has_bduss:
            raise RiskControlException(
                RiskSignal(layer="auth", detail="百度账号未登录或已过期，请到设置页登录"),
                progress=resume_from,
            )

    def _fetch_once(
        self,
        task: MonitorTask,
        keywords: list[str],
        brand: str,
        headless: bool,
        progress_cb: "Callable[[int, int], None] | None" = None,
        cancel_token: Any = None,
        *,
        resume_from: int = 0,
        session: Any = None,
        session_kwargs: "dict[str, Any] | None" = None,
    ) -> MonitorResult:
        """一次完整 多SERP→解 link→抓正文→打分，返回聚合 MonitorResult。

        ``resume_from`` — the absolute 0-based index of the first keyword to
        actually process. Keywords before that index are skipped (they were
        already fetched in a prior run that hit risk control). The
        ``RiskControlException.progress`` value raised inside the loop is
        always the **absolute** keyword index (``resume_from + rel_idx``), so
        the runner's ``last_resumed_keyword = progress + 1`` bookkeeping
        works regardless of whether this is a fresh or resumed run.
        """
        now = datetime.utcnow()

        # Apply resume offset: only iterate keywords[resume_from:]
        # but keep the full list for aggregate stats (total_keywords should
        # reflect the configured list, not just the resumed slice).
        all_keywords = keywords
        keywords_to_fetch = keywords[resume_from:]

        keyword_results: list[dict[str, Any]] = []
        total_kw = len(all_keywords)
        # 全局黑名单 + 任务级 exclude_domains 合并 —— 一次性算好，循环
        # 内每个关键词共用同一份；空 set 等价于不过滤。
        exclude_set = self._build_exclude_set(task)

        # Emit a 0/N progress event up-front so the UI can show the total
        # before the first keyword finishes (otherwise the bar is invisible
        # until ~5–15s in).
        if progress_cb is not None:
            try:
                progress_cb(resume_from, total_kw)
            except Exception:
                logger.exception("progress_cb(resume_from,N) raised; ignoring")

        # CRITICAL: bind the browser session to `bsession`, NOT `session`.
        # Outer `session` is the curl_cffi.Session passed in by fetch() for
        # article HTTP fetches + baidu link resolution. Shadowing it with
        # the BaiduBrowserSession dataclass caused resolve_baidu_link(...,
        # session=session) to receive the wrong type and silently fall
        # through to its default branch (no cookie reuse, no UA pinning),
        # producing the
        #   'BaiduBrowserSession' object has no attribute 'get'
        # warning storm in production logs.
        with baidu_browser_session(headless=headless, **(session_kwargs or {})) as bsession:
            page = bsession.page

            # Login-state pre-flight: an anonymous fetch will burn quickly
            # against baidu 风控. Refuse fast and let the runner pause the
            # task + write a breakpoint; the UI shows "百度账号未登录" + a
            # "前往设置" button. Reusing the live context's cookies avoids
            # opening a second short-lived browser just to read BDUSS.
            cookies = bsession.context.cookies("https://www.baidu.com/")
            self._assert_baidu_logged_in(cookies, resume_from=resume_from)

            for rel_idx, keyword in enumerate(keywords_to_fetch):
                # Absolute 0-based index into the full keyword list.
                kw_idx = resume_from + rel_idx

                # Cooperative cancellation checkpoint —— polled BEFORE we
                # spend more time on the next SERP. The sidecar imports
                # _CancelledFetch from monitor_loop; importing it lazily
                # here keeps csm_core decoupled from sidecar (test runs
                # without sidecar still pass).
                if cancel_token is not None and cancel_token.is_set():
                    try:
                        from csm_sidecar.services.monitor_loop import _CancelledFetch
                    except ImportError:
                        # Lazy fallback: any exception works for the worker —
                        # but the worker won't recognize it as cancellation,
                        # it'll be reported as a generic adapter exception.
                        _CancelledFetch = RuntimeError  # type: ignore[assignment]
                    raise _CancelledFetch(
                        f"cancelled before keyword {kw_idx + 1}/{total_kw}",
                    )

                pacer = rate_limit.get_pacer(self.platform)
                # Only wait between keywords (not before the first one — caller already waited)
                if rel_idx > 0:  # skip wait for first iteration of this scan (caller already waited)
                    pacer.wait()

                serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
                kw_entry: dict[str, Any] = {
                    "keyword": keyword,
                    "serp_url": serp_url,
                    "default_results": [],
                    "news_results": [],
                    "default_matched_count": 0,
                    "default_first_rank": -1,
                    "news_first_rank": -1,
                    "news_present": False,
                    "fetch_error": None,
                }

                serp_response = None
                try:
                    serp_response = _navigate_to_serp(page, keyword)
                except Exception as e:
                    logger.warning(
                        "baidu navigate failed (headless=%s, keyword=%r): %s",
                        headless, keyword, e,
                    )
                    kw_entry["fetch_error"] = f"serp navigate raised: {e!r}"
                    keyword_results.append(kw_entry)
                    # _navigate_to_serp 失败时不调 detect_risk —— 页面没加载，
                    # 4 层信号都没意义。此 keyword 以 fetch_error 状态记录。
                    continue

                # SERP-level login-wall check. Cookie may still be in the
                # jar but baidu's server-side session has expired and the
                # SERP redirects to wappass / passport / shows "请登录" body.
                # Raise auth risk_control so the runner pauses + writes a
                # breakpoint at this keyword index (resume continues here).
                if detect_login_required(serp_response, page):
                    raise RiskControlException(
                        RiskSignal(
                            layer="auth",
                            detail="登录态失效（SERP 跳转登录页），请到设置页重新登录",
                        ),
                        progress=kw_idx,
                    )

                # 4 层风控融合检测（URL + HTTP + DOM + text）。
                # 任一层命中 → 软着陆：弹通知给用户解，解完 retry 当前 kw；失败 fallback 到 raise。
                risk = detect_risk(page, serp_response)
                if risk is not None:
                    solved = _try_human_solve(
                        page=page, keyword=keyword, kw_idx=kw_idx,
                        task_id=task.id,
                        event_publisher=self._event_publisher,
                    )
                    if solved:
                        # 重新 navigate + 重新 detect_risk，本轮 kw 重跑
                        try:
                            serp_response = _navigate_to_serp(page, keyword)
                        except Exception as e:
                            kw_entry["fetch_error"] = f"serp navigate after solve raised: {e!r}"
                            keyword_results.append(kw_entry)
                            continue
                        risk2 = detect_risk(page, serp_response)
                        if risk2 is not None:
                            raise RiskControlException(risk2, progress=kw_idx)
                        # 解完 + 重导成功 → 继续往下走正常 SERP 解析流程
                    else:
                        raise RiskControlException(risk, progress=kw_idx)

                try:
                    serp_html = page.content() or ""
                except Exception as e:
                    kw_entry["fetch_error"] = f"serp page.content raised: {e!r}"
                    keyword_results.append(kw_entry)
                    continue

                parsed = parse_serp(serp_html)
                kw_entry["news_present"] = parsed["news_present"]

                # 抓默认搜索 + 最新资讯两组（pass single brand as list）。
                # exclude_set 过滤 B2B/电商/品牌门户 —— 详见 _check_block。
                default_results = self._check_block(
                    page, parsed["default_links"], [brand, *aliases], block="default",
                    exclude_set=exclude_set,
                    session=session,
                )
                news_results = self._check_block(
                    page, parsed["news_links"], [brand, *aliases], block="news",
                    exclude_set=exclude_set,
                    session=session,
                )

                kw_entry["default_results"] = default_results
                kw_entry["news_results"] = news_results
                matched = [r for r in default_results if r.get("matches_brand")]
                kw_entry["default_matched_count"] = len(matched)
                kw_entry["default_first_rank"] = matched[0]["rank"] if matched else -1
                news_matched = [r for r in news_results if r.get("matches_brand")]
                kw_entry["news_first_rank"] = news_matched[0]["rank"] if news_matched else -1

                keyword_results.append(kw_entry)

                # Notify UI: keyword (kw_idx + 1) of total_kw is done.
                if progress_cb is not None:
                    try:
                        progress_cb(kw_idx + 1, total_kw)
                    except Exception:
                        logger.exception("progress_cb(%s,%s) raised; ignoring", kw_idx + 1, total_kw)

        # Compute task-level aggregations
        total_keywords = len(all_keywords)
        matched_keywords = sum(
            1 for kw in keyword_results if kw["default_matched_count"] > 0
        )
        total_default_matches = sum(kw["default_matched_count"] for kw in keyword_results)
        first_ranks = [kw["default_first_rank"] for kw in keyword_results if kw["default_first_rank"] > 0]
        best_default_first_rank = min(first_ranks) if first_ranks else -1

        metric: dict[str, Any] = {
            "target_brand": brand,
            "brand_aliases": aliases,
            "search_keywords": all_keywords,
            "engine": "patchright",
            "headless": headless,
            "keywords": keyword_results,
            "total_keywords": total_keywords,
            "matched_keywords": matched_keywords,
            "total_default_matches": total_default_matches,
            "best_default_first_rank": best_default_first_rank,
        }

        return MonitorResult(
            task_id=task.id or 0,
            checked_at=now,
            status="ok",
            rank=best_default_first_rank,
            metric=metric,
        )

    def _check_block(
        self,
        page: Any,
        links: list[dict[str, str]],
        brands: list[str],
        *,
        block: str,
        exclude_set: set[str] | None = None,
        session: Any = None,
    ) -> list[dict[str, Any]]:
        """对一组链接逐条抓正文 + 判命中。返回 1-based rank 的 dict 列表。

        ``exclude_set`` —— 在 baidu redirect 解析后做一道域名黑名单过滤
        （命中 jd.com / 1688.com 等 B2B/电商，或者品牌方在 task 配置里
        指定的「自家门户」域名），过滤掉的条目不计入 rank、不占数。
        这样最终的 rank 1, 2, 3 都是"软文/媒体"性质的链接。
        """
        from .. import rate_limit as _rl  # 本地 import 避免循环；rate_limit 是 re-export shim

        out: list[dict[str, Any]] = []
        rank = 0
        for link in links:
            href = resolve_baidu_link(link["href"], session=session)
            host = urlparse(href).netloc or "baidu.com"

            # 早过滤：命中黑名单直接跳过 —— 既不计 rank 也不发文章请求，
            # 节省 1 次 article HTTP 调用。也不调 pacer.wait，避免在被跳过的
            # 条目上空耗几秒。
            if exclude_set and self._is_host_excluded(host, exclude_set):
                logger.debug(
                    "baidu _check_block: skip excluded host %s (link %s)",
                    host, link.get("title", "")[:40],
                )
                continue

            # Article-level pacer —— 关键反爬节流，原来这里就是裸 for 循环
            # 秒级连发 N 条 baidu.com/link 解析 + N 条文章 HTTP 请求，正是
            # 百家号触发验证码的主要诱因。host 是百家号/mbd/mp 时换更宽的
            # 独立 pacer；其它站走 article pacer。RequestPacer 内部维护
            # last_request_at，所以第一条不阻塞（_last_request_at=0 → elapsed
            # 视作 delay_max → sleep_for=0），后续才生效。
            host_lower = host.lower()
            is_baijiahao = any(
                host_lower == h or host_lower.endswith("." + h)
                for h in self._BAIJIAHAO_HOSTS
            )
            pacer_key = (
                self._BAIJIAHAO_PACER_KEY if is_baijiahao else self._ARTICLE_PACER_KEY
            )
            _rl.get_pacer(pacer_key).wait()

            rank += 1
            attempt = fetch_article_http(href, session=session)
            # 方案 B 浏览器兜底（2026-05-28）：HTTP fetch 失败时（403 反爬、
            # JS challenge 壳页、content_len 过短），用副本 Chrome context 的
            # 独立 tab 打开文章 URL → 让 JS 跑完 → 拿 rendered HTML → 提正文。
            #
            # 老注释说"fetch_article_browser disabled to avoid 风控" ── 那是
            # 旧 incognito profile 时代的事：共用 baidu page 风控会迁怒 baidu
            # session。B' 副本模式下 context 是用户日常 Chrome 副本，知乎/
            # smzdm 等站认账（用户日常浏览过），独立 tab 不污染 baidu 主 page，
            # 没风控扩散风险。
            needs_browser = (
                attempt.get("needs_browser_fallback")
                or attempt.get("is_js_challenge")
                or len(attempt.get("content") or "") < _HTTP_MIN_CONTENT_CHARS
            )
            if needs_browser and page is not None:
                try:
                    ctx = getattr(page, "context", None)
                    if ctx is not None:
                        browser_attempt = fetch_article_browser_isolated(ctx, href)
                        if browser_attempt.get("content"):
                            # 浏览器兜底拿到正文 → 替换 HTTP attempt
                            logger.info(
                                "[baidu] browser_isolated fallback: host=%s http_len=%d → browser_len=%d",
                                host, len(attempt.get("content") or ""),
                                len(browser_attempt["content"]),
                            )
                            attempt = browser_attempt
                except Exception as e:
                    logger.warning(
                        "[baidu] browser_isolated fallback raised (host=%s): %s", host, e,
                    )

            content = attempt.get("content") or ""
            matched_brand = match_brand(content, brands)
            # SERP title last-resort fallback：HTTP + browser 都拿不到有效
            # 正文（JS challenge / 验证码反爬 / 内容过短）时，才用 SERP title
            # 匹配 brand。优先级：HTTP 正文 → browser 正文 → title。
            # 只在"彻底拿不到正文"时触发 ── 不影响"正文拿到了但没品牌"的判断
            # （那种是真没命中，不该靠 title 兜）。
            fetch_failed = (
                attempt.get("is_js_challenge")
                or attempt.get("is_blocked")
                or len(content) < _HTTP_MIN_CONTENT_CHARS
            )
            if not matched_brand and fetch_failed:
                title = link.get("title", "")
                title_match = match_brand(title, brands)
                if title_match:
                    matched_brand = title_match
                    logger.info(
                        "[baidu] title fallback matched (正文抓取失败): host=%s brand=%s title=%r",
                        host, matched_brand, title[:80],
                    )
            # 诊断日志（漏检 debug 用）：title / content_len / matched / fetch_error
            # 用 INFO 级让用户开 default log level 就能看到。漏检的 root cause
            # 通常是：① content_len=0（SPA 壳页 / fetch fail）② content_len>200
            # 但 matched=None（正文里没字面品牌词，需要 title fallback）
            logger.info(
                "[baidu] article: rank=%d host=%s content_len=%d matched=%s title=%r%s",
                rank, host, len(content), matched_brand or "-",
                link.get("title", "")[:80],
                f" fetch_error={attempt.get('fetch_error')!r}" if attempt.get("fetch_error") else "",
            )
            out.append({
                "rank": rank,
                "title": link.get("title", ""),
                "url": href,
                "host": host,
                "matches_brand": matched_brand is not None,
                "matched_brand": matched_brand,
                "source": attempt.get("source") or "http",
                "content_preview": content[:160],
                "fetch_error": attempt.get("fetch_error"),
            })
        return out


# Module-level singleton —— 跟其他平台一致。
ADAPTER = BaiduKeywordAdapter()
