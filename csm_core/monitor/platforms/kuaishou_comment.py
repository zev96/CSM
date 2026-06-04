"""Kuaishou comment retention monitor.

Ported from Case-8 ``kuaishou_api.py``. Kuaishou's web API uses a
GraphQL endpoint instead of REST; the only mandatory field on the
request is the cookie + a valid ``photoId`` extracted from the URL.
There is no signing comparable to Douyin's X-Bogus, which is why
Kuaishou tends to be the most stable of the three comment platforms.

URL parsing supports the ``/short-video/...``, ``/video/...``, ``/f/...``
and ``photoId=...`` flavors users typically paste. Failing all of those,
the adapter falls back to fetching the page HTML and grepping for
``"photoId"`` — Case-8 found this catches one or two share-link layouts
that aren't covered by the path regex alone.
"""
from __future__ import annotations
import logging
import re
import threading
from typing import Any

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask, maybe_cancel
from ..rate_limit import get_pacer, get_breaker
from ..drivers.cookie_store import CookieStore
from ._comment_common import (
    build_match_result, fail_result, risk_control_result,
    DEFAULT_SCRAPE_TOP_N, ProgressCb, report_progress,
)

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_PATH_PATTERNS = [
    re.compile(r"/short-video/([a-zA-Z0-9_-]+)"),
    re.compile(r"/video/([a-zA-Z0-9_-]+)"),
    re.compile(r"photoId=([a-zA-Z0-9_-]+)"),
    # ``shareObjectId`` is what the share-redirected URL exposes — quicker
    # than re-grepping the short-video path when both appear in the query
    # string (and matches at the front because we want the *canonical*
    # photoId, not the share token).
    re.compile(r"shareObjectId=([a-zA-Z0-9_-]+)"),
    re.compile(r"/fw/photo/([a-zA-Z0-9_-]+)"),
    re.compile(r"photo/([a-zA-Z0-9_-]+)"),
    # Note: ``/f/<slug>`` is a share-token redirect, NOT a photoId. It is
    # intentionally NOT in this list — the expansion above turns
    # ``/f/<token>`` into ``/short-video/<photoId>`` first; if that
    # expansion fails the HTML fallback below can still recover.
]
_HTML_FALLBACKS = [
    re.compile(r'"photoId"\s*:\s*"([a-zA-Z0-9]+)"'),
    re.compile(r'"photo_id"\s*:\s*"([a-zA-Z0-9]+)"'),
    re.compile(r'data-photo-id="([a-zA-Z0-9]+)"'),
]

# 快手 PC web 评论 GraphQL —— 关键点是 V1 (``rootComments``) 与 V2
# (``rootCommentsV2``) 必须**都**请求。服务器对老查询保持 200 兼容，但只
# 把数据塞进 V2 字段，老的 ``rootComments`` 一直回空数组、``commentCount``
# 回 null —— 之前只查 V1 的版本会得到「HTTP 200 + 0 评论 + 似乎成功」的
# 假阳结果，UI 全部显示"未找到"。快手自家 SPA 的判断（在
# pc-vision/js/short-video.d18beb01.js 里）是 ``rootCommentsV2 !== null
# ? V2 path : V1 path``，下面 ``_fetch_comments`` 对齐这个优先级。
_GQL_QUERY = """
query commentListQuery($photoId: String, $pcursor: String) {
  visionCommentList(photoId: $photoId, pcursor: $pcursor) {
    commentCount
    commentCountV2
    pcursor
    pcursorV2
    rootComments {
      commentId
      authorId
      authorName
      content
      likedCount
      timestamp
    }
    rootCommentsV2 {
      commentId
      authorId
      authorName
      content
      likedCount
      timestamp
    }
  }
}
""".strip()


class KuaishouCommentAdapter:
    platform: str = "kuaishou_comment"

    def __init__(self) -> None:
        self._cookies = CookieStore("kuaishou_comment")
        self._pacer = get_pacer(self.platform)
        self._breaker = get_breaker(self.platform)
        self._ua_idx = 0

    def fetch(
        self,
        task: MonitorTask,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
        **_kwargs,
    ) -> MonitorResult:
        # **_kwargs 吞掉 monitor_loop 的 resume_from 等未来扩展参数。
        # cancel_token 让用户「停止」点击在 fetch 中途生效（不再等整个
        # GraphQL 分页拉完）。
        if not self._breaker.allow():
            return risk_control_result(task, "breaker_open")

        try:
            from curl_cffi import requests as cc_requests
        except ImportError:
            return fail_result(task, "import", "curl_cffi not installed")

        cred = self._cookies.pick()
        ua = (cred.user_agent if cred and cred.user_agent else _USER_AGENTS[self._ua_idx % len(_USER_AGENTS)])
        self._ua_idx += 1
        session = cc_requests.Session(impersonate="chrome120")
        session.headers.update({
            "User-Agent": ua,
            "Origin": "https://www.kuaishou.com",
            "Referer": "https://www.kuaishou.com/",
            "Host": "www.kuaishou.com",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if cred:
            session.headers["Cookie"] = cred.cookies_text

        # Cancel check #1 —— 短链/HTML 解析前快速退出
        maybe_cancel(cancel_token)

        photo_id, err = self._extract_video_id(session, task.target_url)
        if not photo_id:
            return fail_result(task, "extract", err or "could not parse Kuaishou URL")

        # Cancel check #2 —— GraphQL 拉取前再查（最长 15 页 POST 请求）
        maybe_cancel(cancel_token)

        self._pacer.wait()
        scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
        comments, ok, err = self._fetch_comments(
            session, photo_id, limit=scrape_top_n,
            cancel_token=cancel_token, progress_cb=progress_cb,
        )
        if not ok:
            self._breaker.record_failure()
            if cred:
                self._cookies.mark_failed(cred)
            return fail_result(task, "fetch", err or "unknown fetch failure")

        if cred:
            self._cookies.mark_ok(cred)
        self._breaker.record_success()
        return build_match_result(task, comments, source="curl_cffi")

    @staticmethod
    def _extract_video_id(session: Any, raw_url: str) -> tuple[str | None, str]:
        url = raw_url.strip()
        if not url.startswith("http"):
            m = re.search(r"(https?://[^\s]+)", url)
            if not m:
                return None, "no URL found in input"
            url = m.group(1).rstrip("，。！？、/")

        # 快手有两种分享短链格式都会用 ``/f/<slug>``，slug 是 8~16 位的
        # shareToken（如 ``X-7Ellfyy6sQUWfo``），不是 photoId。直接拿 slug
        # 当 photoId 去查 GraphQL，快手会返回空 ``visionCommentList``
        # （HTTP 200 + rootComments=[]），结果是 total_fetched=0、五条任
        # 务全显示"未找到"的假阴性。这里把所有 ``/f/`` 形态都走一次
        # follow-redirects 解析，让重定向后的 ``/short-video/<photoId>``
        # 被下面的 _PATH_PATTERNS 第一条命中。
        is_share_link = "v.kuaishou.com" in url or "kuaishou.com/f/" in url
        if is_share_link:
            try:
                resp = session.get(url, allow_redirects=True, timeout=15)
                if resp.status_code == 200:
                    expanded = str(resp.url)
                    if expanded != url:
                        logger.info(
                            "kuaishou share-link %s expanded to %s",
                            url[:60], expanded[:120],
                        )
                    url = expanded
            except Exception as e:
                logger.info("kuaishou share-link expansion failed: %s", e)

        for pattern in _PATH_PATTERNS:
            m = pattern.search(url)
            if m:
                return m.group(1), ""

        # HTML grep fallback — Case-8 found this catches share-card URLs
        # that don't expose the id in the path.
        if "kuaishou.com" in url:
            try:
                resp = session.get(url, timeout=15)
                if resp.status_code == 200:
                    for fb in _HTML_FALLBACKS:
                        m = fb.search(resp.text)
                        if m:
                            return m.group(1), ""
            except Exception as e:
                logger.info("kuaishou page-scrape fallback failed: %s", e)
        return None, f"could not find photoId in {url[:80]}"

    def _fetch_comments(
        self,
        session: Any,
        photo_id: str,
        limit: int,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        all_comments: list[dict[str, Any]] = []
        pcursor = ""
        api = "https://www.kuaishou.com/graphql"
        for _ in range(15):
            if len(all_comments) >= limit:
                break
            # Cancel check per page —— pacer 可能 sleep 秒级 + GraphQL POST
            # 1-3s，不希望再下载一页才听用户的停止。
            maybe_cancel(cancel_token)
            self._pacer.wait()
            payload = {
                "operationName": "commentListQuery",
                "variables": {"photoId": photo_id, "pcursor": pcursor},
                "query": _GQL_QUERY,
            }
            try:
                resp = session.post(api, json=payload, timeout=20)
            except Exception as e:
                return all_comments, False, f"request raised: {e}"

            if resp.status_code != 200:
                if resp.status_code == 400:
                    return all_comments, False, "HTTP 400 — cookie likely invalid"
                return all_comments, False, f"HTTP {resp.status_code}"
            try:
                data = resp.json()
            except Exception:
                return all_comments, False, "non-JSON response (likely risk control)"

            if "errors" in data:
                msg = (data["errors"][0] or {}).get("message", "unknown")
                return all_comments, False, f"GraphQL error: {msg}"

            vision = (data.get("data") or {}).get("visionCommentList") or {}
            # 与快手 SPA 同步：V2 字段非空就走 V2，否则降级 V1。新 PC web
            # 现在只填 V2；保留 V1 兜底是给未来变更或老版本兜底用。
            roots_v2 = vision.get("rootCommentsV2")
            roots = roots_v2 if roots_v2 else (vision.get("rootComments") or [])
            if not roots:
                break
            for c in roots:
                if len(all_comments) >= limit:
                    break
                text = c.get("content") or ""
                if not text:
                    continue
                all_comments.append({
                    "rank": len(all_comments) + 1,
                    "text": text,
                    "author": c.get("authorName") or "",
                    "likes": int(c.get("likedCount") or 0),
                })

            report_progress(progress_cb, len(all_comments), limit)
            new_pcursor = (
                vision.get("pcursorV2") if roots_v2 else vision.get("pcursor")
            ) or ""
            if not new_pcursor or new_pcursor == "no_more" or new_pcursor == pcursor:
                break
            pcursor = new_pcursor

        return all_comments, True, None


ADAPTER = KuaishouCommentAdapter()
