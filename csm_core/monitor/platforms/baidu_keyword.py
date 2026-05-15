"""百度关键词排名监控 adapter。

策略：
1. 用 patchright incognito 打开 baidu.com/s?wd=keyword（默认 headless）
2. 用 spec 给的 XPath 抓「默认搜索」「最新资讯」两个区块的 h3//a href
3. 解 baidu.com/link?url=... 跳转拿真实 URL
4. 对每条 URL：curl_cffi + readability 抓正文，识别失败 fallback 浏览器
5. 大小写不敏感匹配任一 target_brand → matches_brand=True

引擎硬绑 patchright（无痕需 BrowserContext API，drission 不支持）。
"""
from __future__ import annotations

import logging
from typing import Any

from lxml import html as lxml_html

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
def _cc_get(url: str, **kwargs: Any) -> Any:
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, **kwargs)


def resolve_baidu_link(url: str) -> str:
    """如果是 baidu.com/link?url=... 跳转，跟随 redirect 拿真实 URL。

    非百度跳转 URL 直接返回。任何异常 → 返回原 URL（adapter 自然把它当
    抓取失败 source）。
    """
    if not url or "baidu.com/link?" not in url:
        return url
    try:
        resp = _cc_get(
            url,
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


def fetch_article_http(url: str) -> dict[str, Any]:
    """用 curl_cffi + readability 抓单篇文章，返回纯文本正文。

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
    content = _extract_readable_text(raw)
    if len(content) < _HTTP_MIN_CONTENT_CHARS:
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


class BaiduKeywordAdapter:
    """`BaseMonitorAdapter` 实现。完整 fetch 在后续任务里逐步加上。"""

    platform: str = "baidu_keyword"

    def __init__(self) -> None:
        # 真实字段在 apply_settings 里被覆盖。
        self._headless_default = True
        self._captcha_timeout_s = 90
        self._captcha_max_promotions = 1

    def apply_settings(
        self,
        *,
        headless_default: bool = True,
        captcha_visible_timeout_s: int = 90,
        captcha_max_promotions: int = 1,
        serp_pacing_seconds: int = 5,
        breaker_failures: int = 3,
        breaker_cooldown_seconds: int = 600,
    ) -> None:
        """挂接 settings.monitor.baidu_keyword.*。lifecycle 启动 + 设置页保存时各调一次。"""
        from ..rate_limit import get_pacer, get_breaker

        self._headless_default = headless_default
        self._captcha_timeout_s = captcha_visible_timeout_s
        self._captcha_max_promotions = captcha_max_promotions

        pacer = get_pacer(self.platform)
        # 把 spec 的 serp_pacing_seconds 映射成 pacer 的 (min, max) jitter 窗口。
        pacer.configure(
            delay_min=float(serp_pacing_seconds),
            delay_max=float(serp_pacing_seconds * 2),
        )
        breaker = get_breaker(self.platform)
        breaker.failure_threshold = breaker_failures
        breaker.cool_off_seconds = float(breaker_cooldown_seconds)

    def fetch(self, task):  # noqa: ANN001 — full annotation in later task
        """先返回失败结果，完整实现见后续任务。"""
        from datetime import datetime
        from ..base import MonitorResult
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="failed",
            rank=-1,
            error_message="baidu_keyword adapter not yet implemented",
        )


# Module-level singleton —— 跟其他平台一致。
ADAPTER = BaiduKeywordAdapter()
