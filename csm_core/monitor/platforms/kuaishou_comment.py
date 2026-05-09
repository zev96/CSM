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
from typing import Any

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask
from ..rate_limit import get_pacer, get_breaker
from ..drivers.cookie_store import CookieStore
from ._comment_common import build_match_result, fail_result, risk_control_result

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_PATH_PATTERNS = [
    re.compile(r"/short-video/([a-zA-Z0-9_-]+)"),
    re.compile(r"/video/([a-zA-Z0-9_-]+)"),
    re.compile(r"photoId=([a-zA-Z0-9_-]+)"),
    re.compile(r"/f/([a-zA-Z0-9_-]+)"),
    re.compile(r"/fw/photo/([a-zA-Z0-9_-]+)"),
    re.compile(r"photo/([a-zA-Z0-9_-]+)"),
]
_HTML_FALLBACKS = [
    re.compile(r'"photoId"\s*:\s*"([a-zA-Z0-9]+)"'),
    re.compile(r'"photo_id"\s*:\s*"([a-zA-Z0-9]+)"'),
    re.compile(r'data-photo-id="([a-zA-Z0-9]+)"'),
]

_GQL_QUERY = """
query commentListQuery($photoId: String, $pcursor: String) {
  visionCommentList(photoId: $photoId, pcursor: $pcursor) {
    commentCount
    pcursor
    rootComments {
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

    def fetch(self, task: MonitorTask) -> MonitorResult:
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

        photo_id, err = self._extract_video_id(session, task.target_url)
        if not photo_id:
            return fail_result(task, "extract", err or "could not parse Kuaishou URL")

        self._pacer.wait()
        comments, ok, err = self._fetch_comments(session, photo_id, limit=200)
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

        if "v.kuaishou.com" in url:
            try:
                resp = session.get(url, allow_redirects=True, timeout=15)
                if resp.status_code == 200:
                    url = str(resp.url)
            except Exception as e:
                logger.info("kuaishou short-link expansion failed: %s", e)

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
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        all_comments: list[dict[str, Any]] = []
        pcursor = ""
        api = "https://www.kuaishou.com/graphql"
        for _ in range(15):
            if len(all_comments) >= limit:
                break
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
            roots = vision.get("rootComments") or []
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

            new_pcursor = vision.get("pcursor") or ""
            if not new_pcursor or new_pcursor == "no_more" or new_pcursor == pcursor:
                break
            pcursor = new_pcursor

        return all_comments, True, None


ADAPTER = KuaishouCommentAdapter()
