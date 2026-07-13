"""百度关键词排名监控 adapter。

策略：
1. 用 patchright incognito 打开 baidu.com/s?wd=keyword（默认 headless）
2. 抓「默认搜索」「最新资讯」两个区块的 h3//a href（默认区块 2026-07 起用
   token 级 class 选择器 + tpl 黑名单，另带 content_left 兜底，见 _XPATH_DEFAULT）
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
import re
import threading
import time
import unicodedata
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


# ── 「默认搜索」区块选择器 ──────────────────────────────────────────
# 本质契约：按 DOM 顺序枚举左栏 organic 结果卡，取每张卡的 h3/a。
# 稳定信号：c-container class token（多年未变）、tpl 模板名、h3/a 标题链接；
# 易变信号：class token 的集合与顺序 —— 2026-07 改版把 'result' token 整个
# 去掉（旧选择器 contains(@class,'result') 因此 0 命中、假报"无排名"），
# 所以只 token 级匹配仍存在的标记，不依赖顺序、不依赖已消失的 token。
#
# 非文章杂卡按 tpl 模板名排除（漏排会污染 rank + 白抓一次正文）。
# 2026-07 实测发现百度按会话分发**两套模板桶**，杂卡 tpl 两桶都要覆盖：
#   登录桶（用户日常 Chrome / 副本 profile，adapter 实际运行环境）——
#     sp_purc_pc            购物 / 推广卡
#     short_video           短视频卡（两桶都有）
#     news-realtime         实时资讯卡（2025 旧名，保留防旧结构回滚）
#     rel_base_realtime     实时资讯卡（2026-07 用户实测观察到的新名）
#     b2b_factory_wise_san  B2B 工厂卡（爱采购，2026-07 用户实测观察到）
#   匿名桶（www_index 系模板，2026-07-03 live 探针观察；organic=www_index）——
#     b2b_prod              爱采购商品批发卡（实测会抢 rank #1）
#     image_grid_san        图片网格卡
#     recommend_list        相关推荐 / 大家还在搜
#     uer_feedback          用户反馈卡
#     new_baikan_index      百看图文视频聚合
#     note_lead             笔记类聚合卡
_EXCLUDED_TPLS: tuple[str, ...] = (
    "sp_purc_pc",
    "short_video",
    "news-realtime",
    "rel_base_realtime",
    "b2b_factory_wise_san",
    "b2b_prod",
    "image_grid_san",
    "recommend_list",
    "uer_feedback",
    "new_baikan_index",
    "note_lead",
)


def _class_token(token: str) -> str:
    """token 级 class 匹配（等价 CSS 的 ``.token``）。

    contains(@class, 'x') 是子串匹配，会把 'x-y' / 'prefix-x' 也算进来；
    补空格哨兵后只命中完整 token，且与 token 在 class 里的顺序无关。
    """
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {token} ')"


# tpl 黑名单，主 / 兜底两条选择器共用（单一来源不漂移）。
#
# 2026-07 起不再排除含 span.cosc-title-slot 的卡：旧版里它标记知识图谱卡，
# 但 live 探针实测它已变成普通结果卡的通用标题槽（一页 11 个），保留该
# 排除会把 6 条 organic 误杀到只剩 1 条杂卡。误杀（区块全空）是灾难性
# 失败，偶尔混入一张知识卡（1 条 rank 污染 + 1 次白抓）代价小得多 ——
# 结构性排除只在"标记语义稳定"时才成立。
# normalize-space 与 class 匹配同款加固：tpl 属性若带意外空白也不绕过黑名单。
_COMMON_EXCLUDES = " and ".join(
    f"not(normalize-space(@tpl)='{t}')" for t in _EXCLUDED_TPLS
)

_XPATH_DEFAULT = (
    "//div["
    + " and ".join((
        _class_token("c-container"),
        _class_token("xpath-log"),
        _class_token("new-pmd"),
    ))
    + " and " + _COMMON_EXCLUDES
    + "]//h3/a"
)

# 兜底选择器：xpath-log / new-pmd 是"时代标记"（new-pmd 即 2020 改版产物），
# 下一次改版可能像 'result' 一样消失。主选择器 0 命中时退化为只认
# c-container token，但收窄到 content_left 主结果列（十余年未变的结构锚点）
# 控制过抓，右栏杂卡不会混入。
_XPATH_DEFAULT_RELAXED = (
    "//div[@id='content_left']//div["
    + _class_token("c-container")
    + " and " + _COMMON_EXCLUDES
    + "]//h3/a"
)

_XPATH_NEWS = (
    "//div[contains(@class, 'cos-space')]"
    "/div[contains(@class, 'cos-row')]"
    "//h3//a"
)

def parse_serp(html: str) -> dict[str, Any]:
    """从一段 SERP HTML 抽取两组 (title, href) 链接。

    纯函数：不发请求、不解 redirect、不判断品牌词 —— 只把 DOM 翻成 list。

    ``selector_fallback`` —— True 表示主选择器 0 命中、结果来自兜底
    c-container 选择器（百度 DOM 大概率又改版了；随 metric 落库留痕，
    方便回溯是哪天开始走兜底的）。
    """
    if not html or not html.strip():
        return {"default_links": [], "news_links": [], "news_present": False,
                "selector_fallback": False}

    try:
        doc = lxml_html.fromstring(html)
    except Exception as e:
        logger.warning("baidu parse_serp: lxml fromstring raised: %s", e)
        return {"default_links": [], "news_links": [], "news_present": False,
                "selector_fallback": False}

    selector_fallback = False
    default_links = _extract_a_tags(doc, _XPATH_DEFAULT)
    # 兜底选择器每次都算（sub-ms）：既是主选择器 0 命中时的替补，也是
    # "部分漂移哨兵"的对照组 —— 只靠"主 0 才兜底"的开关，看不见
    # 「部分 organic 卡丢 token、主选择器返回非空子集」这种静默漏抓。
    relaxed_links = _extract_a_tags(doc, _XPATH_DEFAULT_RELAXED)
    if not default_links:
        if relaxed_links:
            default_links = relaxed_links
            selector_fallback = True
            logger.warning(
                "baidu parse_serp: 主选择器 0 命中，content_left 兜底命中 %d 条 "
                "—— 百度 SERP DOM 可能已改版，请核对 _XPATH_DEFAULT。tpls=%s",
                len(relaxed_links), _tpl_inventory(doc),
            )
        else:
            # 真实 SERP 默认区块不可能是空的（无结果页 / 风控漏检除外），
            # 双选择器 0 命中几乎必是 DOM 改版。把关键统计打进日志留证据 ——
            # 只返回空 list 的 silent failure 没法区分改版 / 风控 / 空页多种根因。
            logger.warning(
                "baidu parse_serp: 默认区块主 + 兜底选择器均 0 命中 "
                "html_len=%d c-container=%d h3=%d tpls=%s body_first200=%r",
                len(html),
                html.count("c-container"),
                len(doc.xpath("//h3")),
                _tpl_inventory(doc),
                _extract_raw_body_text(html)[:200],
            )
    else:
        # 部分漂移哨兵：兜底(只认 c-container)比主选择器多出条目，说明
        # content_left 里有卡丢了 xpath-log / new-pmd 时代 token —— 主选择器
        # 正在静默漏抓。行为不变（仍用主选择器结果），只告警留证据。
        primary_hrefs = {l["href"] for l in default_links}
        extra = [l for l in relaxed_links if l["href"] not in primary_hrefs]
        if extra:
            logger.warning(
                "baidu parse_serp: 兜底选择器比主选择器多 %d 条（主 %d / 兜底 %d）"
                "—— 部分结果卡可能丢了时代 token，主选择器或在静默漏抓。"
                "多出样例=%r tpls=%s",
                len(extra), len(default_links), len(relaxed_links),
                [(e["title"][:30], e["href"][:60]) for e in extra[:3]],
                _tpl_inventory(doc),
            )

    news_links = _extract_a_tags(doc, _XPATH_NEWS)
    if not news_links:
        # 资讯区静默死亡观测：cos-space 容器存在但一行都没解出 ≠ 页面没有
        # 资讯区（后者常见且正常）—— 前者是内层结构（cos-row/h3）漂移信号。
        try:
            cos_blocks = int(doc.xpath("count(//div[contains(@class, 'cos-space')])"))
        except Exception:
            cos_blocks = 0
        if cos_blocks:
            logger.warning(
                "baidu parse_serp: 页面存在 %d 个 cos-space 资讯容器但解出 0 行 "
                "—— 资讯区内层结构可能已变更，请核对 _XPATH_NEWS",
                cos_blocks,
            )
    return {
        "default_links": default_links,
        "news_links": news_links,
        "news_present": bool(news_links),
        "selector_fallback": selector_fallback,
    }


# T4 来源预过滤：从 SERP 结果卡的可见 showurl 抽真实来源 host。只认
# source/showurl/siteLink 语义类（不认泛用的 c-color-gray —— 它也用于日期/
# 摘要，会把标题或摘要里出现的域名误当来源）。抽不到就 None（fail-open：
# _check_block 照常 resolve 后过滤，零回归）。
_SHOWURL_HOST_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}", re.I
)
_SHOWURL_XPATH = (
    ".//*[contains(@class,'showurl') or contains(@class,'source') "
    "or contains(@class,'siteLink') or contains(@class,'site-link')]"
)


def _showurl_host(a_node: Any) -> str | None:
    """从结果 <a> 所在 c-container 抽可见来源 host（供排除域名预过滤）。

    走 source/showurl 语义元素的文本，正则抠第一个域名。显示名（"知乎"）
    或 DOM 改版找不到元素时返回 None —— 调用方 fail-open 走原 resolve 路径。
    """
    try:
        containers = a_node.xpath(
            "ancestor::div[" + _class_token("c-container") + "][1]"
        )
        if not containers:
            return None
        container = containers[0]
        # 防误杀（结构排除=灾难）：一个 c-container 内有多条结果标题锚点时（资讯簇
        # cos-space 一卡含 N 条 / 聚合卡），showurl 无法可靠归属到当前这一条 ——
        # 若在整容器里抠"第一个域名"，簇内某条的排除域名会污染整簇被一起预过滤掉。
        # 这种情况直接 fail-open（None），退回原 resolve 后按各自真实 host 过滤。
        if len(container.xpath(".//h3//a")) > 1:
            return None
        parts = container.xpath(_SHOWURL_XPATH + "//text()")
        text = " ".join(p.strip() for p in parts if p and p.strip())
        if not text:
            return None
        m = _SHOWURL_HOST_RE.search(text)
        if not m:
            return None
        return m.group(0).lower().strip(".") or None
    except Exception:
        return None


# R1 摘要兜底：从结果卡抽 SERP 摘要文本，供正文抓取失败时再判一层命中（软文
# 品牌常出现在摘要里）。只用于"抓取失败"的弱兜底，不替代正文抓取、不写跨轮缓存。
_SNIPPET_XPATH = (
    ".//*[contains(@class,'abstract') or contains(@class,'c-span-last') "
    "or contains(@class,'content-right')]//text()"
)


def _result_snippet(a_node: Any) -> str:
    """从结果 <a> 所在 c-container 抽 SERP 摘要文本。多结果容器（资讯簇）
    fail-open 返回 ""（防簇内摘要串味造成假命中）。"""
    try:
        containers = a_node.xpath(
            "ancestor::div[" + _class_token("c-container") + "][1]"
        )
        if not containers:
            return ""
        container = containers[0]
        if len(container.xpath(".//h3//a")) > 1:
            return ""
        parts = container.xpath(_SNIPPET_XPATH)
        return " ".join(p.strip() for p in parts if p and p.strip())[:500]
    except Exception:
        return ""


def _extract_a_tags(doc: Any, xpath: str) -> list[dict[str, Any]]:
    """跑一条 XPath 抓所有 <a>，返回 [{title, href, show_host, snippet}]。

    ``show_host`` —— SERP 可见来源 host（c-showurl），供 _check_block 在
    resolve 之前预过滤排除域名；抽不到为 None。
    ``snippet`` —— SERP 摘要文本，正文抓取失败时的兜底命中信号；抽不到为 ""。
    """
    try:
        nodes = doc.xpath(xpath)
    except Exception as e:
        logger.warning("baidu xpath %r raised: %s", xpath, e)
        return []
    out: list[dict[str, Any]] = []
    for a in nodes:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        # 标题文本：百度 h3 里通常有 <em> 高亮，textcontent 直接拿到纯文本
        title = (a.text_content() or "").strip()
        out.append({
            "title": title, "href": href,
            "show_host": _showurl_host(a), "snippet": _result_snippet(a),
        })
    return out


# T5 跨轮正向命中缓存 —— 同进程内、TTL 有界、只存确定性正向。
# 语义：同一 resolved URL 上一轮已确认命中某 brand → 本轮跳过正文抓取直接判
# 命中（省一次文章 HTTP + 潜在验证码，尤其 smzdm/百家号）。rank 永远按本轮
# SERP 位置算（位次新鲜），只短路「这篇文章是否含品牌」这一步。
#
# 准确性护栏：① 只存正向（未命中/失败从不缓存 → 永远重查）② 默认 TTL 6h：
# 日更任务跨天必过期→全新抓取零陈旧，只加速同进程内频繁重跑 ③ 复用要求缓存
# 的 brand 在本任务品牌列表里（多任务隔离）。进程重启即冷 = fail-safe。
_CROSS_RUN_HIT_TTL_SECONDS = 6 * 3600
_CROSS_RUN_HIT_MAX = 2000  # 正向命中很少（只用户自家软文），上限只防异常膨胀


def _cross_run_lookup(
    cache: "dict[str, tuple[str, float]] | None", url: str, brands: list[str]
) -> str | None:
    """返回缓存里 url 的 matched_brand（未过期且 brand ∈ brands），否则 None。"""
    if not cache:
        return None
    entry = cache.get(url)
    if entry is None:
        return None
    matched_brand, expiry = entry
    if time.monotonic() >= expiry:
        cache.pop(url, None)  # 过期即清理
        return None
    return matched_brand if matched_brand in brands else None


def _cross_run_remember(
    cache: "dict[str, tuple[str, float]] | None", url: str, matched_brand: str | None
) -> None:
    """把确定性正向命中写进缓存（未命中/None 不写）。有界防膨胀。"""
    if cache is None or not matched_brand:
        return
    if len(cache) >= _CROSS_RUN_HIT_MAX and url not in cache:
        now = time.monotonic()
        # 快照 list(...) 再迭代，避免与并发写撞 "dict changed size during iteration"
        # （调用点已加锁，这里再兜一层）。
        for k in [k for k, (_, exp) in list(cache.items()) if exp <= now]:
            cache.pop(k, None)
        if len(cache) >= _CROSS_RUN_HIT_MAX:
            return  # fail-safe：满了就不缓存新条目，只是少一点提速收益
    cache[url] = (matched_brand, time.monotonic() + _CROSS_RUN_HIT_TTL_SECONDS)


def _tpl_inventory(doc: Any) -> dict[str, int]:
    """content_left 里所有带 tpl 的 div 盘点（纯诊断）。

    这套选择器的下一次失效大概率是 tpl 名变化（news-realtime →
    rel_base_realtime 一年内就发生过）—— 把清单直接打进告警日志，
    远程看日志就能定位新 organic / 杂卡 tpl 名，不用给用户发 debug 版。
    """
    inv: dict[str, int] = {}
    try:
        for t in doc.xpath("//div[@id='content_left']//div/@tpl"):
            key = (t or "").strip() or "(empty)"
            inv[key] = inv.get(key, 0) + 1
    except Exception:
        pass
    return inv


def match_brand(content: str, brands: list[str]) -> str | None:
    """大小写不敏感找首个出现的目标品牌词。

    "首个" 的含义是 brands 列表里的顺序，不是 content 中位置 ——
    用户排品牌词顺序代表优先级（主品牌排前面）。

    Args:
        content: 待检测正文（不限长度，但建议先 readability 提过）
        brands: 目标品牌词列表，至少非空才有意义

    Returns:
        命中的品牌词原文（保留 brands 列表里的大小写），无命中 → None

    匹配规则：
    - 两侧都做 NFKC 归一 + lower：全角品牌名（ＮＯＶＡ）与半角配置（NOVA）
      等价，避免因宽度差异漏检。
    - 纯 ASCII 字母数字品牌（Nova / MOVA / 3M）要求**词边界**，避免
      "Nova" 命中 "innovation"、"MOVA" 命中 "removal" 这类子串误报 —— 尤其
      raw-body fallback 会喂全站 nav/JS 文本，一个误命中就把整站文章误判成
      命中。
    - 含 CJK / 空格 / 符号的品牌（小米 / Coca Cola）无词边界概念，走子串。
    """
    if not content or not brands:
        return None
    content_norm = unicodedata.normalize("NFKC", content).lower()
    for brand in brands:
        if not brand:
            continue
        b_norm = unicodedata.normalize("NFKC", brand).lower()
        if not b_norm:
            continue
        if b_norm.isascii() and b_norm.isalnum():
            # 词边界：品牌前后不能紧挨字母/数字
            if re.search(
                r"(?<![a-z0-9])" + re.escape(b_norm) + r"(?![a-z0-9])",
                content_norm,
            ):
                return brand
        elif b_norm in content_norm:
            return brand
    return None


def _all_keywords_failed(keyword_results: list[dict[str, Any]]) -> bool:
    """每个关键词都带 fetch_error（SERP 导航失败 / content 抓取失败）才算
    「整轮失败」。用来区分「浏览器/网络在每个关键词上都挂了」（→ 返回
    failed，触发熔断、不把断网误报成「监测完成」）和「合法地没搜到结果」
    （fetch_error=None）。空列表不算失败（没跑不等于失败）。"""
    return bool(keyword_results) and all(
        kw.get("fetch_error") for kw in keyword_results
    )


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

# 验证码/风控插页的 body text 很短（验证码说明 + 按钮），正文页很长。用这个
# 阈值区分：只有 body text 短于它时才信 text 层的风控关键词，避免长文章正文
# 里出现「网络异常/系统繁忙」等词被误判成风控。与 _is_captcha_page 对齐。
_CAPTCHA_BODY_MIN_CHARS = 800


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
            impersonate="chrome131",
            allow_redirects=True,
            timeout=15,
            # 从 SERP 点进文章的真实流量形状：带 baidu Referer + cross-site。
            # 裸访问（Sec-Fetch-Site:none、无 Referer）对百家号等强风控站是
            # 明显机器人特征。session 模式下这些 per-request header 覆盖 session
            # 默认（session 默认给 warmup 打 baidu.com 用的 same/none）。
            headers={
                "Referer": "https://www.baidu.com/",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
            },
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
    # url / http 层可靠，照跑。text 层最易误报（长文章正文里出现「网络异常/
    # 系统繁忙/验证码」等词是正常内容）—— 只在 body 很短（真验证码/风控插页
    # 特征，与 _is_captcha_page 的 800 阈值对齐）时才信它。
    risk = detect_risk_by_url(final_url) or detect_risk_by_http(resp)
    if risk is None and len(_extract_raw_body_text(raw)) < _CAPTCHA_BODY_MIN_CHARS:
        risk = detect_risk_by_text(raw)
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

    注意：lxml 的 ``text_content()`` **不会**自动剔除 <script>/<style>（旧
    注释说会是错的，已实测证伪）。body 里的 inline JS/CSS 会被一起拼进来，
    污染 match_brand（品牌名出现在全站 JS 常量 / 埋点里 → 假命中）并让
    _is_captcha_page 的 800 字符阈值失真。所以先删掉这些节点再取文本。
    """
    if not raw_html.strip():
        return ""
    try:
        doc = lxml_html.fromstring(raw_html)
    except Exception as e:
        logger.info("raw body text extraction failed: %s", e)
        return ""
    if doc is None:
        return ""
    # drop_tree() 保留节点的 tail 文本，只删元素本体 —— 比 parent.remove 更稳。
    for el in doc.xpath("//script | //style | //noscript | //template"):
        try:
            el.drop_tree()
        except Exception:
            pass
    body = doc.find(".//body")
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
    surfaced = False
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
            # 关键：把屏外窗口浮上来 + 激活文章 tab。native 模式窗口恒停在
            # -32000 屏外（见 offscreen_args），只发通知不上浮 → 用户根本看不到
            # 要解的验证码 → 180s 必然空等超时、is_blocked、正文抓不到。这正是
            # 「什么值得买验证码难搞」的直接根因。SERP 级 _try_human_solve 有
            # surface_window，article 级一直漏了。
            try:
                new_page.bring_to_front()
                surface_window(new_page)
                surfaced = True
            except Exception:
                logger.warning("[baidu] surface article-captcha window failed", exc_info=True)
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
            # 解完/超时后把窗口推回屏外，恢复默认 offscreen 状态（下一个
            # 关键词 SERP 不该看见残留窗口）。hide 必须在 close 之前 —— 关了
            # tab 就拿不到 CDP session 了。
            if surfaced:
                try:
                    hide_window(new_page)
                except Exception:
                    logger.debug("[baidu] hide article-captcha window failed", exc_info=True)
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
    # 百度自有垂类 host —— 永不计入排名、不抓正文（精确匹配，2026-07）。
    # cosc 知识卡结构排除移除后的补偿守卫：百科等垂类页正文天然含品牌词
    # （搜品牌词出来的词条必然写着品牌名），计入会假报「自家软文排第 N」；
    # 自搜索链接（www.baidu.com/s?wd=）用 curl 直连还会白白刺激风控。
    # 注意：① 百家号 baijiahao/mbd/mp 是真实文章宿主，绝不能进此名单；
    # ② 只做 host 精确匹配、不做后缀匹配（后缀 baidu.com 会误杀百家号）；
    # ③ 裸 "baidu.com" 条目兜住相对 href 解析失败时的占位 host；
    # ④ 不随 use_default_excludes 关闭 —— 这是正确性守卫，不是用户偏好。
    _NON_ARTICLE_HOSTS: frozenset[str] = frozenset({
        "baidu.com",
        "www.baidu.com",
        "baike.baidu.com",
        "b2b.baidu.com",
        "image.baidu.com",
        "haokan.baidu.com",
    })

    def __init__(self) -> None:
        # 真实字段在 apply_settings 里被覆盖。
        # 百度恒有头（见 _run 里 effective_headless）—— 这个默认值现已不参与决策，
        # 留作语义标记。
        self._headless_default = False
        # 默认 300s：接线前 _try_human_solve 恒用其 300s 死默认，保持该窗口不缩短。
        self._captcha_timeout_s = 300
        # 每关键词每区块抓满 N 条排名结果就停（省尾部抓取）。0=不封顶（默认，
        # 保持准确不漏 page 1 的 11-13 位）；用户可在设置页按需开启换速度。
        self._article_rank_cap = 0
        # 默认排除域名（B2B / 电商）。apply_settings 会用 config 里的值
        # 覆盖；空 list 表示「不应用全局黑名单」（用户在设置页清空时）。
        self._default_excluded_domains: tuple[str, ...] = ()
        # per-task curl_cffi.Session 池。Session 内含 cookie jar，per-task 复用
        # 让 BAIDUID / BIDUPSID baseline cookie 不被频繁丢弃 → 降低风控触发率。
        self._http_sessions: dict[int, Any] = {}
        self._http_sessions_lock = threading.Lock()
        self._event_publisher: Any = None
        # T5 跨轮正向命中缓存：resolved URL → (matched_brand, expiry_monotonic)。
        # 存活于 adapter 单例（跨 fetch() 调用持续），进程重启即冷。见
        # _cross_run_lookup / _cross_run_remember 的准确性护栏。
        self._cross_run_hits: dict[str, tuple[str, float]] = {}
        # 保护跨轮缓存的读写。百度常态 concurrency=1（串行），但若 apply_settings
        # 在 configure_concurrency 之前抛错，信号量会惰性回退成 2 → 两个百度任务
        # 并发 → prune 迭代 dict 时被并发写触发 RuntimeError。跟 _http_sessions_lock
        # 同理加锁兜底（未争用时开销可忽略）。
        self._cross_run_lock = threading.Lock()

    def set_event_publisher(self, fn: Any) -> None:
        """Sidecar lifespan 启动时注入，给 native mode chrome_preflight +
        软着陆验证码 发 SSE 事件用。"""
        self._event_publisher = fn

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
            # impersonate 自带自洽的 UA + sec-ch-ua client hints，别再用 UA 池
            # 覆盖 User-Agent（旧代码 3/4 会话 UA 说 Windows 而 client hints 说
            # macOS，指纹自相矛盾 = 机器人特征）。用较新的 chrome131 而非 2023 的
            # chrome120（陈旧指纹本身也是 flag）。
            sess = cc_requests.Session(impersonate="chrome131")
            sess.headers.update({
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
        captcha_visible_timeout_s: int = 300,
        serp_pacing_seconds: int = 5,
        article_pacing_seconds: int = 3,
        baijiahao_pacing_seconds: int = 8,
        breaker_failures: int = 3,
        breaker_cooldown_seconds: int = 600,
        default_excluded_domains: list[str] | tuple[str, ...] | None = None,
        article_fetch_rank_cap: int = 0,
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
        self._article_rank_cap = max(0, int(article_fetch_rank_cap))
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
        partial_cb: "Callable[[int, list], None] | None" = None,
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
                aliases=aliases,
                resume_from=resume_from,
                partial_cb=partial_cb,
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
        aliases: list[str],
        resume_from: int = 0,
        partial_cb: "Callable[[int, list], None] | None" = None,
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
                aliases=aliases,
                resume_from=resume_from,
                partial_cb=partial_cb,
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
        (``next_kw = progress``) stays consistent — nothing was fetched in
        this run, so resume from the same index (``resume_from``).
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
        aliases: list[str],
        resume_from: int = 0,
        partial_cb: "Callable[[int, list], None] | None" = None,
        session: Any = None,
        session_kwargs: "dict[str, Any] | None" = None,
    ) -> MonitorResult:
        """一次完整 多SERP→解 link→抓正文→打分，返回聚合 MonitorResult。

        ``resume_from`` — the absolute 0-based index of the first keyword to
        actually process. Keywords before that index are skipped (they were
        already fetched in a prior run that hit risk control). The
        ``RiskControlException.progress`` value raised inside the loop is
        always the **absolute** keyword index (``resume_from + rel_idx``) of
        the keyword that hit risk — which was NOT yet appended (raise happens
        before append). The runner resumes from that index itself
        (``next_kw = progress``, NOT progress+1), so the failing keyword is
        re-scraped rather than skipped. Works for fresh or resumed runs.

        ``aliases`` 必须由 fetch() 解析后 **显式传进来**（和 ``brand`` 同款 thread
        路径：fetch → _fetch_with_promotion → _fetch_once）。别在本方法里就地从
        task.config 重算 —— brand_aliases 功能（86e9018）当初就是把 ``aliases = ...``
        放在 fetch() 而 ``[brand, *aliases]`` 用在这里，跨方法作用域导致
        NameError("name 'aliases' is not defined")，整条抓取被当 adapter exception。
        设成 keyword-only 必填，漏传会在调用点立刻报错（fail-loud）。
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
        # 「本轮已验证码超时」host 集合 —— 跨关键词/跨 block 共享，某 host
        # 软着陆超时后不再对同 host 反复空等 180s（run 级去重）。
        captcha_timeout_hosts: set[str] = set()
        # 本轮 URL memo —— 跨关键词/跨 block 共享，同一篇文章只抓一次正文。
        article_memo: dict[str, dict[str, Any]] = {}

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
                    "selector_fallback": False,
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
                        # 带出本轮已抓完的头段（本 run 的 resume_from..kw_idx-1）；
                        # runner 再与上次断点的 [0..resume_from-1] 合并存全量头段。
                        partial_keywords=keyword_results,
                    )

                # 4 层风控融合检测（URL + HTTP + DOM + text）。
                # 任一层命中 → 软着陆：弹通知给用户解，解完 retry 当前 kw；失败 fallback 到 raise。
                risk = detect_risk(page, serp_response)
                if risk is not None:
                    solved = _try_human_solve(
                        page=page, keyword=keyword, kw_idx=kw_idx,
                        task_id=task.id,
                        event_publisher=self._event_publisher,
                        # 接线配置项：让设置页「验证码可见超时」真正生效（原来恒
                        # 走 _try_human_solve 的 300s 死默认，配置存了不用）。
                        timeout_s=self._captcha_timeout_s,
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
                            raise RiskControlException(
                                risk2, progress=kw_idx, partial_keywords=keyword_results
                            )
                        # 解完 + 重导成功 → 继续往下走正常 SERP 解析流程
                    else:
                        raise RiskControlException(
                            risk, progress=kw_idx, partial_keywords=keyword_results
                        )

                try:
                    serp_html = page.content() or ""
                except Exception as e:
                    kw_entry["fetch_error"] = f"serp page.content raised: {e!r}"
                    keyword_results.append(kw_entry)
                    continue

                parsed = parse_serp(serp_html)
                kw_entry["news_present"] = parsed["news_present"]
                kw_entry["selector_fallback"] = parsed.get("selector_fallback", False)

                # 抓默认搜索 + 最新资讯两组（pass single brand as list）。
                # exclude_set 过滤 B2B/电商/品牌门户 —— 详见 _check_block。
                default_results = self._check_block(
                    page, parsed["default_links"], [brand, *aliases], block="default",
                    exclude_set=exclude_set,
                    session=session,
                    captcha_timeout_hosts=captcha_timeout_hosts,
                    article_memo=article_memo,
                    cross_run_cache=self._cross_run_hits,
                    rank_cap=self._article_rank_cap,
                    cancel_token=cancel_token,
                )
                news_results = self._check_block(
                    page, parsed["news_links"], [brand, *aliases], block="news",
                    exclude_set=exclude_set,
                    session=session,
                    captcha_timeout_hosts=captcha_timeout_hosts,
                    article_memo=article_memo,
                    cross_run_cache=self._cross_run_hits,
                    # rank cap 只作用于默认结果区（用户「只看前 N 名排名」的语义就是默认
                    # 结果）；资讯区通常很小，不封顶，避免「设 10 实际抓到约 20」的意外。
                    rank_cap=0,
                    cancel_token=cancel_token,
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

                # R2 增量落库：把本轮已抓完的头段（[resume_from:kw_idx+1]）flush 给
                # runner 落草稿。next_kw=kw_idx+1 是绝对下一个待抓下标（崩溃后从这里
                # 续）。传 list(...) 浅拷贝快照，避免消费方存引用被后续 append 污染。
                if partial_cb is not None:
                    try:
                        partial_cb(kw_idx + 1, list(keyword_results))
                    except Exception:
                        logger.exception("partial_cb(%s) raised; ignoring", kw_idx + 1)

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

        # 整轮每个关键词都抓取失败（断网 / 副本 Chrome 坏）→ 返回 failed 而不是
        # 「ok + 空表」。否则 runner 会弹「监测任务完成」、熔断器还被 record_success
        # 重置，掩盖真故障。合法「没搜到结果」（fetch_error=None）不受影响。
        if _all_keywords_failed(keyword_results):
            first_err = next(
                (kw.get("fetch_error") for kw in keyword_results if kw.get("fetch_error")),
                None,
            )
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=now,
                status="failed",
                rank=-1,
                metric=metric,
                error_message=f"全部 {len(keyword_results)} 个关键词抓取失败：{first_err}",
            )

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
        captcha_timeout_hosts: set[str] | None = None,
        article_memo: dict[str, dict[str, Any]] | None = None,
        cross_run_cache: "dict[str, tuple[str, float]] | None" = None,
        rank_cap: int = 0,
        cancel_token: Any = None,
    ) -> list[dict[str, Any]]:
        """对一组链接逐条抓正文 + 判命中。返回 1-based rank 的 dict 列表。

        ``exclude_set`` —— 在 baidu redirect 解析后做一道域名黑名单过滤
        （命中 jd.com / 1688.com 等 B2B/电商，或者品牌方在 task 配置里
        指定的「自家门户」域名），过滤掉的条目不计入 rank、不占数。
        这样最终的 rank 1, 2, 3 都是"软文/媒体"性质的链接。

        ``captcha_timeout_hosts`` —— 跨 block/keyword 共享的「本轮已验证码超时」
        host 集合。某 host 软着陆超时后加进来，后续同 host 结果不再进隔离 tab
        空等 180s。None 时用本地集合（只在本次调用内短路）。

        ``article_memo`` —— 跨 block/keyword 共享的「本轮已抓正文」缓存（resolved
        URL → attempt）。同一篇文章常在多个关键词的 SERP 里重复出现，命中直接
        复用正文/命中结果，跳过 pacer + HTTP + 浏览器兜底。None 时不缓存。
        """
        from .. import rate_limit as _rl  # 本地 import 避免循环；rate_limit 是 re-export shim

        if captcha_timeout_hosts is None:
            captcha_timeout_hosts = set()
        out: list[dict[str, Any]] = []
        rank = 0
        for link in links:
            # R3 协作取消检查点：每条文章前查一次令牌，让「停止」在关键词内即时
            # 生效（原来一个关键词内 10+ 篇 × 节流，停止最多要等约 5min）。
            if cancel_token is not None and cancel_token.is_set():
                try:
                    from csm_sidecar.services.monitor_loop import _CancelledFetch
                except ImportError:
                    _CancelledFetch = RuntimeError  # type: ignore[assignment]
                raise _CancelledFetch("cancelled mid-keyword (before next article)")

            # R4 rank cap：抓满 N 条排名结果就停（省尾部文章抓取）。默认 rank_cap=0
            # 不封顶——全量抓取保持准确（百度只取 page 1，封顶会漏 11-13 位，故设为
            # 用户可选、默认关）。排除/垂类跳过的条目不占 rank，不受影响。
            if rank_cap > 0 and rank >= rank_cap:
                break

            # T4 来源预过滤：SERP 可见 host（c-showurl）已是排除域名 → 在 resolve
            # 之前就跳过，省一次 /link 跳转解析。show_host=None（显示名 / DOM 改版
            # 抽不到）时不预过滤，走原 resolve 后过滤路径，零回归。结果与 resolve
            # 后过滤一致：不占 rank、不发文章请求、不调 pacer。
            show_host = (link.get("show_host") or "").lower().strip()
            if show_host and exclude_set and self._is_host_excluded(show_host, exclude_set):
                logger.info(
                    "baidu _check_block: prefilter skip excluded show_host %s (link %s)",
                    show_host, link.get("title", "")[:40],
                )
                continue

            href = resolve_baidu_link(link["href"], session=session)
            host = urlparse(href).netloc or "baidu.com"

            # 跳转解析失败守卫：resolve 返回的仍是 baidu.com/link?… → 没拿到
            # 真实 URL（超时 / 异常，或被风控页拦住没跟 302）。这条的 host 会
            # 被算成 www.baidu.com 恰好命中下面的 _NON_ARTICLE_HOSTS 而被静默
            # 跳过 —— 那会让这条（可能正是用户软文）从排名里凭空消失、后面所有
            # 位次前移；resolve session 被软封时整表全空却报 status=ok。必须占
            # 一个 rank 位、用 SERP title 尽力判命中、并标 fetch_error。
            if "baidu.com/link?" in href:
                rank += 1
                title = link.get("title", "")
                title_match = match_brand(title, brands)
                logger.warning(
                    "[baidu] _check_block: 跳转未解析，占位 rank=%d（跳过垂类守卫）"
                    " title=%r matched=%s",
                    rank, title[:60], title_match or "-",
                )
                out.append({
                    "rank": rank,
                    "title": title,
                    "url": href,
                    "host": host,
                    "matches_brand": title_match is not None,
                    "matched_brand": title_match,
                    "source": "unresolved",
                    "fetch_error": "跳转链接解析失败（未拿到真实 URL）",
                })
                continue

            # 百度自有垂类守卫：百科 / 自搜索 / 图片 / 好看等永不是"软文
            # 文章"本体，直接跳过（不计 rank、不发请求、不调 pacer）。
            # 见 _NON_ARTICLE_HOSTS 注释。
            if host.lower() in self._NON_ARTICLE_HOSTS:
                logger.info(
                    "baidu _check_block: skip baidu vertical host %s (link %s)",
                    host, link.get("title", "")[:40],
                )
                continue

            # 早过滤：命中黑名单直接跳过 —— 既不计 rank 也不发文章请求，
            # 节省 1 次 article HTTP 调用。也不调 pacer.wait，避免在被跳过的
            # 条目上空耗几秒。
            if exclude_set and self._is_host_excluded(host, exclude_set):
                logger.debug(
                    "baidu _check_block: skip excluded host %s (link %s)",
                    host, link.get("title", "")[:40],
                )
                continue

            host_lower = host.lower()
            rank += 1

            # T5 跨轮正向命中缓存：同一 URL 上一轮（≤TTL）已确认命中本任务某品牌
            # → 直接判命中、跳过正文抓取（省文章 HTTP + 潜在验证码）。rank 已按
            # 本轮 SERP 位置算好（位次永远新鲜），这里只短路「是否含品牌」。
            with self._cross_run_lock:
                cross_hit = _cross_run_lookup(cross_run_cache, href, brands)
            if cross_hit is not None:
                logger.info(
                    "[baidu] cross-run cache hit: rank=%d host=%s brand=%s url=%s",
                    rank, host, cross_hit, href[:80],
                )
                out.append({
                    "rank": rank,
                    "title": link.get("title", ""),
                    "url": href,
                    "host": host,
                    "matches_brand": True,
                    "matched_brand": cross_hit,
                    "source": "cache",
                    "fetch_error": None,
                })
                continue

            # 本轮 URL memo：同一篇文章常在多个关键词的 SERP 里重复出现（93 个
            # 品牌相关关键词头部结果高度重叠）。命中直接复用正文/命中结果，跳过
            # pacer + HTTP + 浏览器兜底 —— 省 30-50% 文章抓取，且请求更少 = 反爬
            # 暴露更低。只缓存拿到正文的确定性正向结果，避免把 transient 失败
            # 传染给后续同 URL 的关键词。
            attempt = article_memo.get(href) if article_memo is not None else None
            if attempt is None:
                # Article-level pacer —— 关键反爬节流，原来这里就是裸 for 循环
                # 秒级连发 N 条 baidu.com/link 解析 + N 条文章 HTTP 请求，正是
                # 百家号触发验证码的主要诱因。host 是百家号/mbd/mp 时换更宽的
                # 独立 pacer；其它站走 article pacer。RequestPacer 内部维护
                # last_request_at，所以第一条不阻塞（_last_request_at=0 → elapsed
                # 视作 delay_max → sleep_for=0），后续才生效。
                is_baijiahao = any(
                    host_lower == h or host_lower.endswith("." + h)
                    for h in self._BAIJIAHAO_HOSTS
                )
                pacer_key = (
                    self._BAIJIAHAO_PACER_KEY if is_baijiahao else self._ARTICLE_PACER_KEY
                )
                _rl.get_pacer(pacer_key).wait()

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
                # 百度自家风控页（verify.baidu.com / safetycheck）：fetch_article_http
                # 已明确 needs_browser_fallback=False —— 进隔离 tab 只会在真登录
                # context 里反复打开 verify.baidu.com 并 180s 空等。尊重它，别让
                # 下面「content 太短」的长度条款把风控页强行拉进浏览器兜底。
                is_baidu_risk = (attempt.get("fetch_error") or "").startswith("百度风控")
                needs_browser = (not is_baidu_risk) and (
                    attempt.get("needs_browser_fallback")
                    or attempt.get("is_js_challenge")
                    or len(attempt.get("content") or "") < _HTTP_MIN_CONTENT_CHARS
                )
                # 同 host 一轮只软着陆一次：某 host 上一条软着陆验证码超时
                # （is_blocked）后，本轮后续同 host 结果不再进隔离 tab 空等 180s
                # （一页 3 条 smzdm 否则 = 3×180s）。
                if needs_browser and host_lower in captcha_timeout_hosts:
                    logger.info(
                        "[baidu] skip browser fallback: host %s 本轮已验证码超时", host_lower,
                    )
                    needs_browser = False
                if needs_browser and page is not None:
                    try:
                        ctx = getattr(page, "context", None)
                        if ctx is not None:
                            browser_attempt = fetch_article_browser_isolated(ctx, href)
                            if browser_attempt.get("is_blocked"):
                                captcha_timeout_hosts.add(host_lower)
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

                # 只缓存拿到正文的确定性正向结果 —— transient 失败不进 memo，让
                # 后续同 URL 关键词各自重试（且失败页多半已被 captcha_timeout_hosts
                # 或 baidu_risk 短路，不会真的反复打）。
                if article_memo is not None and attempt.get("content"):
                    article_memo[href] = attempt

            content = attempt.get("content") or ""
            matched_brand = match_brand(content, brands)
            # 是否来自"真·正文命中"（而非下面的 title fallback）—— 只有正文命中才
            # 够确定性、值得写进跨轮缓存；title fallback 是抓取失败下的弱兜底，
            # 缓存它会把一次瞬时失败的 title-only 判定钉死 TTL 期，掩盖文章其实
            # 可抓 / 可能已不含品牌。
            matched_from_content = matched_brand is not None
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
                else:
                    # R1 摘要兜底：标题也没命中时，再用 SERP 摘要判一层（软文品牌常
                    # 出现在摘要里）。同样只在正文彻底抓不到时触发，且 matched_from_content
                    # 仍为 False → 弱兜底命中不写跨轮缓存。
                    snippet = link.get("snippet", "") or ""
                    snip_match = match_brand(snippet, brands) if snippet else None
                    if snip_match:
                        matched_brand = snip_match
                        logger.info(
                            "[baidu] snippet fallback matched (正文+标题都未命中): host=%s brand=%s",
                            host, matched_brand,
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
                "fetch_error": attempt.get("fetch_error"),
            })
            # T5：只把"真·正文命中"写进跨轮缓存供后续 run 复用（title fallback
            # 命中不写 —— 见 matched_from_content 注释）；未命中/弱兜底都不写。
            if matched_from_content and matched_brand:
                with self._cross_run_lock:
                    _cross_run_remember(cross_run_cache, href, matched_brand)
        return out


# Module-level singleton —— 跟其他平台一致。
ADAPTER = BaiduKeywordAdapter()
