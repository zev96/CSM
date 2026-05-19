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
from datetime import datetime
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


def _navigate_to_serp(page: Any, keyword: str) -> Any:
    """直接 goto SERP url。返回 navigation response 给 detect_risk 用。

    回归原架构 —— 三段式 home/fill/Enter 的时间 pattern 反而是 bot 信号。
    带登录态（BDUSS）的直接 goto 看起来像真实用户从书签或外链进 SERP，
    是 baidu organic 流量的主要形态。
    """
    serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
    return page.goto(serp_url, wait_until="domcontentloaded", timeout=30000)


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
        self._headless_default = True
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

        # Clamp resume_from to valid range so callers don't need to guard.
        resume_from = max(0, min(int(resume_from), len(keywords)))

        session = self._get_session(task.id or 0)
        try:
            return self._fetch_with_promotion(
                task, keywords, brand, headless, progress_cb, cancel_token,
                resume_from=resume_from,
                session=session,
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
        with baidu_browser_session(headless=headless) as bsession:
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
                # 任一层命中 → 抛 RiskControlException，runner (Task 4) 捕获写断点。
                risk = detect_risk(page, serp_response)
                if risk is not None:
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
                    page, parsed["default_links"], [brand], block="default",
                    exclude_set=exclude_set,
                    session=session,
                )
                news_results = self._check_block(
                    page, parsed["news_links"], [brand], block="news",
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
            # NOTE: browser fallback (fetch_article_browser) is intentionally
            # disabled here. It used to upgrade short-content fetches to a
            # patchright open in the SAME baidu profile, which shares the
            # logged-in BDUSS cookie. baidu treats 10 rapid baijiahao opens
            # by a logged-in user as bot behaviour → captcha on the article
            # page → detect_risk_by_text catches "验证码" → RiskControlException
            # → entire task aborts at breakpoint 0 even though SERP succeeded.
            # HTTP-only article fetches with curl_cffi keep article retrieval
            # decoupled from the baidu session. Short / JS-heavy pages just
            # get content_preview=""; matches_brand judgement degrades to
            # title+summary, which is acceptable. Proper fix is the two-phase
            # design in docs/superpowers/specs/2026-05-19-baidu-two-phase-fetch-design.md.
            if attempt.get("needs_browser_fallback"):
                attempt["fetch_error"] = (
                    attempt.get("fetch_error")
                    or "HTTP extraction failed; browser fallback disabled to avoid 风控"
                )

            content = attempt.get("content") or ""
            matched_brand = match_brand(content, brands)
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
