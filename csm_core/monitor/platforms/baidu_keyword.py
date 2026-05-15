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
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, quote

from lxml import html as lxml_html

from .. import rate_limit
from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask
from ..drivers.incognito_session import incognito_session, is_baidu_captcha_url

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


def fetch_article_browser(page: Any, url: str) -> dict[str, Any]:
    """浏览器 fallback：用已有的 patchright Page 打开 URL，读 HTML 提正文。

    跟 HTTP-first 函数返回结构一致，方便上游统一处理。

    复用同一个 incognito context 的 Page —— SERP 抓完后，循环里
    每条 URL 在同 page 上 goto 切走（不开新 tab，避免句柄爆炸）。
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except TypeError:
        # FakePage 不接受关键字参数：测试场景
        try:
            page.goto(url)
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


class BaiduKeywordAdapter:
    """`BaseMonitorAdapter` 实现。SERP → 解链 → 抓正文 → 品牌匹配 → MonitorResult。

    新模型：config.search_keywords (list[str]) + config.target_brand (str)。
    每个 keyword 跑一次独立 SERP，结果聚合到 metric.keywords[] + task 级统计。

    引擎硬绑 patchright incognito。验证码命中时尝试 headless→可见升级（最多
    ``_captcha_max_promotions`` 次），全失败则 status=risk_control。
    """

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

    def fetch(self, task: MonitorTask) -> MonitorResult:
        breaker = rate_limit.get_breaker(self.platform)
        if not breaker.allow():
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="risk_control",
                rank=-1,
                error_message="circuit breaker open for baidu_keyword",
            )

        cfg = task.config or {}
        keywords_raw = cfg.get("search_keywords") or []
        keywords = [k.strip() for k in keywords_raw if k and k.strip()]
        brand = (cfg.get("target_brand") or "").strip()

        if not keywords or not brand:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="config.search_keywords (non-empty list) + target_brand required",
            )

        headless = bool(cfg.get("headless", self._headless_default))
        rate_limit.get_pacer(self.platform).wait()

        return self._fetch_with_promotion(task, keywords, brand, headless)

    def _fetch_with_promotion(
        self,
        task: MonitorTask,
        keywords: list[str],
        brand: str,
        headless: bool,
    ) -> MonitorResult:
        """跑一次所有 SERP；命中验证码且还有升级机会 → headless=False 再跑一次（全重跑）。"""
        breaker = rate_limit.get_breaker(self.platform)
        promotions_left = self._captcha_max_promotions
        last_attempt_headless = headless
        captcha_hit_overall = False

        while True:
            try:
                result = self._fetch_once(task, keywords, brand, last_attempt_headless)
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

            captcha_hit_overall = captcha_hit_overall or result.metric.get("captcha_hit", False)
            if result.status == "risk_control" and result.metric.get("captcha_hit"):
                if promotions_left > 0 and last_attempt_headless:
                    logger.info(
                        "baidu captcha hit; promoting to visible (%d promotions left)",
                        promotions_left,
                    )
                    promotions_left -= 1
                    last_attempt_headless = False
                    continue
                # 用尽升级机会，或者本来就在 visible 还命中
                result.metric["captcha_hit"] = True
                breaker.record_failure()
                return result

            if result.status == "ok":
                breaker.record_success()
            else:
                breaker.record_failure()
            # 把 captcha_hit_overall 写回去，前端用得到
            result.metric["captcha_hit"] = captcha_hit_overall
            return result

    def _fetch_once(
        self,
        task: MonitorTask,
        keywords: list[str],
        brand: str,
        headless: bool,
    ) -> MonitorResult:
        """一次完整 多SERP→解 link→抓正文→打分，返回聚合 MonitorResult。"""
        now = datetime.utcnow()

        # 用于 risk_control 的 minimal metric（captcha hit 时快速返回）
        empty_metric: dict[str, Any] = {
            "target_brand": brand,
            "search_keywords": keywords,
            "engine": "patchright",
            "headless": headless,
            "captcha_hit": False,
            "keywords": [],
            "total_keywords": len(keywords),
            "matched_keywords": 0,
            "total_default_matches": 0,
            "best_default_first_rank": -1,
        }

        keyword_results: list[dict[str, Any]] = []
        captcha_hit = False

        with incognito_session(headless=headless) as session:
            page = session.page

            for keyword in keywords:
                pacer = rate_limit.get_pacer(self.platform)
                # Only wait between keywords (not before the first one — caller already waited)
                if keyword != keywords[0]:
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

                # Navigate to SERP. 45s timeout — baidu 偶尔冷启慢，20s 不够。
                try:
                    page.goto(serp_url, wait_until="domcontentloaded", timeout=45000)
                except TypeError:
                    # Test FakePage 不接受 kwargs
                    page.goto(serp_url)
                except Exception as e:
                    logger.warning(
                        "baidu navigate failed (headless=%s, keyword=%r): %s",
                        headless, keyword, e,
                    )
                    kw_entry["fetch_error"] = f"serp navigate raised: {e!r}"
                    keyword_results.append(kw_entry)
                    continue

                landed_url = getattr(page, "url", "") or ""
                if is_baidu_captcha_url(landed_url):
                    captcha_hit = True
                    kw_entry["fetch_error"] = f"captcha at {landed_url[:120]}"
                    keyword_results.append(kw_entry)
                    # Break on captcha — return risk_control immediately
                    break

                try:
                    serp_html = page.content() or ""
                except Exception as e:
                    kw_entry["fetch_error"] = f"serp page.content raised: {e!r}"
                    keyword_results.append(kw_entry)
                    continue

                parsed = parse_serp(serp_html)
                kw_entry["news_present"] = parsed["news_present"]

                # 抓默认搜索 + 最新资讯两组（pass single brand as list）
                default_results = self._check_block(
                    page, parsed["default_links"], [brand], block="default",
                )
                news_results = self._check_block(
                    page, parsed["news_links"], [brand], block="news",
                )

                kw_entry["default_results"] = default_results
                kw_entry["news_results"] = news_results
                matched = [r for r in default_results if r.get("matches_brand")]
                kw_entry["default_matched_count"] = len(matched)
                kw_entry["default_first_rank"] = matched[0]["rank"] if matched else -1
                news_matched = [r for r in news_results if r.get("matches_brand")]
                kw_entry["news_first_rank"] = news_matched[0]["rank"] if news_matched else -1

                keyword_results.append(kw_entry)

        if captcha_hit:
            empty_metric["captcha_hit"] = True
            empty_metric["keywords"] = keyword_results
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=now,
                status="risk_control",
                rank=-1,
                metric=empty_metric,
                error_message="baidu captcha hit during keyword SERP",
            )

        # Compute task-level aggregations
        total_keywords = len(keywords)
        matched_keywords = sum(
            1 for kw in keyword_results if kw["default_matched_count"] > 0
        )
        total_default_matches = sum(kw["default_matched_count"] for kw in keyword_results)
        first_ranks = [kw["default_first_rank"] for kw in keyword_results if kw["default_first_rank"] > 0]
        best_default_first_rank = min(first_ranks) if first_ranks else -1

        metric: dict[str, Any] = {
            "target_brand": brand,
            "search_keywords": keywords,
            "engine": "patchright",
            "headless": headless,
            "captcha_hit": False,
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
    ) -> list[dict[str, Any]]:
        """对一组链接逐条抓正文 + 判命中。返回 1-based rank 的 dict 列表。"""
        out: list[dict[str, Any]] = []
        for i, link in enumerate(links, start=1):
            href = resolve_baidu_link(link["href"])
            host = urlparse(href).netloc or "baidu.com"

            attempt = fetch_article_http(href)
            if attempt.get("needs_browser_fallback"):
                attempt = fetch_article_browser(page, href)

            content = attempt.get("content") or ""
            matched_brand = match_brand(content, brands)
            out.append({
                "rank": i,
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
