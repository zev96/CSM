"""Douyin comment retention monitor.

Ported from Case-8 ``douyin_api.py``. The X-Bogus signature is the
weakest link — Case-8's note explicitly flagged its hash-based stub as
"likely unusable" because Douyin enforces a real signature derived from
the request URL via a JS algorithm. We keep the same stub here so the
adapter compiles and runs end-to-end, but expect Douyin to be the first
platform to need a Playwright/JS-VM signing path. The plan's risk
register already covers this.

URL parsing handles three flavors users actually paste:

- Long URL: ``https://www.douyin.com/video/{aweme_id}``
- Modal URL: ``https://www.douyin.com/...modal_id={aweme_id}``
- Share text: ``...复制此消息打开抖音 https://v.douyin.com/abc/...``

Short URLs are resolved via a redirect to the long form.
"""
from __future__ import annotations
import hashlib
import logging
import re
import threading
from typing import Any
from urllib.parse import urlencode

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

_VIDEO_ID_PATTERNS = [
    re.compile(r"/video/(\d+)"),
    re.compile(r"/note/(\d+)"),
    re.compile(r"modal_id=(\d+)"),
    re.compile(r"aweme_id=(\d+)"),
]


class DouyinCommentAdapter:
    platform: str = "douyin_comment"

    def __init__(self) -> None:
        self._cookies = CookieStore("douyin_comment")
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
        # cancel_token 是协作取消（用户点「停止」时 monitor_loop set 它）。
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
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if cred:
            session.headers["Cookie"] = cred.cookies_text

        # Cancel check #1 —— 短链解析前快速退出
        maybe_cancel(cancel_token)

        # 1. Resolve URL → aweme_id, expanding short links if needed.
        aweme_id, err = self._extract_video_id(session, task.target_url)
        if not aweme_id:
            return fail_result(task, "extract", err or "unknown URL parse error")

        # Cancel check #2 —— 进入主拉取（最长 15 页）前再查一次
        maybe_cancel(cancel_token)

        # 2. Fetch comment list with X-Bogus signed query (best-effort).
        self._pacer.wait()
        scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
        comments, ok, err = self._fetch_comments(
            session, aweme_id, limit=scrape_top_n,
            cancel_token=cancel_token, progress_cb=progress_cb,
        )
        if not ok:
            self._breaker.record_failure()
            if cred:
                self._cookies.mark_failed(cred)
            if err and ("captcha" in err.lower() or "验证" in err):
                return risk_control_result(task, "captcha")
            return fail_result(task, "fetch", err or "unknown fetch failure")

        if cred:
            self._cookies.mark_ok(cred)
        self._breaker.record_success()
        return build_match_result(task, comments, source="curl_cffi")

    # ── URL → aweme_id ─────────────────────────────────────────────────────
    @staticmethod
    def _extract_video_id(session: Any, raw_url: str) -> tuple[str | None, str]:
        url = raw_url.strip()
        if not url.startswith("http"):
            m = re.search(r"(https?://[^\s]+)", url)
            if not m:
                return None, "could not find a URL in the input"
            url = m.group(1).rstrip("，。！？、/")

        # Resolve short link via a follow-redirects HEAD/GET. Failures
        # here are not fatal — some short links carry the id in the path
        # and the regex below picks them up directly.
        if "v.douyin.com" in url:
            try:
                resp = session.get(url, allow_redirects=True, timeout=15)
                if resp.status_code == 200:
                    url = str(resp.url)
            except Exception as e:
                logger.info("douyin short-link expansion failed: %s — falling back", e)

        for pattern in _VIDEO_ID_PATTERNS:
            m = pattern.search(url)
            if m:
                return m.group(1), ""
        return None, "could not extract aweme_id from URL"

    # ── Comments fetch + X-Bogus stub ──────────────────────────────────────
    def _fetch_comments(
        self,
        session: Any,
        aweme_id: str,
        limit: int,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        all_comments: list[dict[str, Any]] = []
        cursor = 0
        api = "https://www.douyin.com/aweme/v1/web/comment/list/"
        # Page cap — same reasoning as Bilibili: a runaway page loop
        # signals risk control truncating responses.
        for _ in range(15):
            if len(all_comments) >= limit:
                break
            # Cancel check per page —— pacer 可能 sleep 秒级 + 请求 1-3s，
            # 不想再翻一页才听取消。
            maybe_cancel(cancel_token)
            self._pacer.wait()
            params: dict[str, Any] = {
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "aweme_id": aweme_id,
                "cursor": cursor,
                "count": 20,
                "version_code": "170400",
                "version_name": "17.4.0",
            }
            params["X-Bogus"] = self._generate_x_bogus(urlencode(params))
            try:
                resp = session.get(api, params=params, timeout=20)
            except Exception as e:
                return all_comments, False, f"request raised: {e}"

            if resp.status_code != 200:
                return all_comments, False, f"HTTP {resp.status_code}"

            try:
                data = resp.json()
            except Exception:
                text = resp.text or ""
                if "验证" in text or "captcha" in text.lower():
                    return all_comments, False, "captcha challenged — refresh cookie"
                if "登录" in text or "login" in text.lower():
                    return all_comments, False, "login required — provide cookie"
                return all_comments, False, "non-JSON response (likely risk control)"

            for c in data.get("comments") or []:
                if len(all_comments) >= limit:
                    break
                text = c.get("text") or ""
                if not text:
                    continue
                all_comments.append({
                    "rank": len(all_comments) + 1,
                    "text": text,
                    "author": (c.get("user") or {}).get("nickname", ""),
                    "likes": int(c.get("digg_count") or 0),
                })

            report_progress(progress_cb, len(all_comments), limit)
            if data.get("has_more") != 1:
                break
            cursor = int(data.get("cursor") or cursor + 20)

        return all_comments, True, None

    @staticmethod
    def _generate_x_bogus(params_str: str) -> str:
        # Stand-in signature. Documented in plan risk register: when this
        # silently breaks (Douyin returns empty data), swap in a real JS
        # signing implementation. Kept here so the adapter compiles and
        # the rest of the pipeline can be exercised end-to-end.
        try:
            md5 = hashlib.md5(params_str.encode("utf-8")).hexdigest()
            return f"DFSzswVZNAG{md5[:8]}"
        except Exception:
            return "DFSzswVZNAG8SbG8haF"


ADAPTER = DouyinCommentAdapter()
