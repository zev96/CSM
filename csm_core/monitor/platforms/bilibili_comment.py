"""Bilibili comment retention monitor.

Ported from Case-8 ``bilibili_api.py`` with the following changes:

- ``requests`` → ``curl_cffi`` to avoid being fingerprinted as scripted
  traffic (Bilibili's WAF is the source of the 412 risk-control returns
  Case-8 had to defend against).
- Cookies come from :class:`CookieStore` instead of a hard-coded module
  constant, so multi-account rotation is possible.
- Two-pass fetch (mode=3 hot + mode=2 time fallback) is preserved, but
  the dedup-by-text and rank-numbering logic now lives inside this
  adapter rather than in a separate ``CommentDetectorV2`` class.
"""
from __future__ import annotations
import logging
import re
import threading
from typing import Any

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask, maybe_cancel
from ..rate_limit import get_pacer, get_breaker
from ..drivers.cookie_store import CookieStore
from ..text_match import DEFAULT_SIMILARITY_THRESHOLD
from ._comment_common import (
    build_match_result, fail_result, risk_control_result,
    DEFAULT_SCRAPE_TOP_N, ProgressCb, report_progress,
)
from ._comment_shared import CommentSnapshot, result_from_snapshot, shared_store

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_BV_RE = re.compile(r"(BV[a-zA-Z0-9]+)")
_AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)


class BilibiliCommentAdapter:
    platform: str = "bilibili_comment"

    def __init__(self) -> None:
        self._cookies = CookieStore("bilibili_comment")
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
        # **_kwargs swallows monitor_loop 的 resume_from 等未来扩展参数。
        # cancel_token 是真正用到的协作取消信号 —— 用户在 UI 点「停止」
        # 时 monitor_loop 会 set 它，本函数沿途多处 maybe_cancel(...) 检查
        # 后立刻退出（避免完整跑完一次 fetch 才听取消）。
        my_text = str(task.config.get("my_comment_text") or "").strip()
        if not my_text:
            # 缺评论文本必然 failed —— 提前返回，别为坏配置白抓一轮。
            return build_match_result(task, [], source="curl_cffi")
        threshold = float(task.config.get("threshold") or DEFAULT_SIMILARITY_THRESHOLD)
        scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
        store = shared_store()
        task_id = task.id or 0

        vid_info = self._extract_video_id(task.target_url)
        if not vid_info:
            return fail_result(task, "extract", f"could not parse Bilibili URL: {task.target_url}")
        vid, id_type = vid_info
        # BV 与 av 是同一视频的两种写法，但解析是纯正则、无从互认 —— 键上
        # 带 id_type，同写法的任务共享（批量导入同视频的行 URL 一致）。
        share_key = ("local", self.platform, f"{id_type}:{vid}")

        # ① 同视频快照复用（纯内存）：同一条视频下的多条评论任务只有第一
        #    个真正抓评论区（含 BV→aid 解析），其余对共享快照匹配。
        snap = store.peek(
            share_key, task_id=task_id,
            my_text=my_text, threshold=threshold, depth=scrape_top_n,
        )
        if snap is not None:
            return result_from_snapshot(task, snap, source="curl_cffi")

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
            "Origin": "https://www.bilibili.com",
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if cred:
            session.headers["Cookie"] = cred.cookies_text

        # Cancel check #1 —— pacer wait 之前快速退出
        maybe_cancel(cancel_token)

        def do_fetch() -> CommentSnapshot:
            # 真实抓取 + 全部簿记（pacer / 熔断 / cookie 标记）只由 fetcher
            # 执行一次；BV→aid 解析也是网络请求，一并只付一次。
            # 1. Resolve BV → AID. Bilibili's reply API takes the numeric aid
            # (oid), not the BV. The /x/web-interface/view endpoint returns
            # both for free.
            self._pacer.wait()
            maybe_cancel(cancel_token)
            aid = self._resolve_aid(session, vid, id_type)
            if not aid:
                self._breaker.record_failure()
                if cred:
                    self._cookies.mark_failed(cred)
                return CommentSnapshot(
                    depth=scrape_top_n, error="could not resolve AV/BV → aid",
                    error_source="resolve_aid",
                )

            # Cancel check #2 —— 进入主评论拉取（最长 20 页 × 数百毫秒）前再查
            maybe_cancel(cancel_token)

            # 2. Pull hot comments (mode=3). If we don't have enough, top up
            # with mode=2 (time-sorted) but mark those rank=-1 so the matcher
            # only counts the hot-sorted slice.
            hot, ok, err = self._fetch_comments_by_mode(
                session, aid, mode=3, limit=scrape_top_n,
                cancel_token=cancel_token, progress_cb=progress_cb,
            )
            if not ok:
                self._breaker.record_failure()
                if cred:
                    self._cookies.mark_failed(cred)
                if err and "412" in err:
                    return CommentSnapshot(
                        depth=scrape_top_n, error=err, risk_source="http_412",
                    )
                return CommentSnapshot(
                    depth=scrape_top_n, error=err or "unknown",
                    error_source="fetch_hot",
                )
            if cred:
                self._cookies.mark_ok(cred)
            self._breaker.record_success()
            return CommentSnapshot(
                comments=hot, depth=scrape_top_n,
                exhausted=len(hot) < scrape_top_n,
            )

        snap = store.run(
            share_key, task_id=task_id,
            my_text=my_text, threshold=threshold, depth=scrape_top_n,
            cancel_token=cancel_token, do_fetch=do_fetch,
        )
        return result_from_snapshot(task, snap, source="curl_cffi")

    # ── HTTP helpers ───────────────────────────────────────────────────────
    def _resolve_aid(self, session: Any, vid: str, id_type: str) -> str | None:
        if id_type == "avid":
            return vid
        try:
            resp = session.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": vid},
                timeout=15,
            )
            if resp.status_code != 200 or resp.text.strip().startswith("<"):
                return None
            data = resp.json()
            if data.get("code") == 0:
                return str(data["data"]["aid"])
        except Exception as e:
            logger.info("bilibili aid resolve failed: %s", e)
        return None

    def _fetch_comments_by_mode(
        self,
        session: Any,
        aid: str,
        mode: int,
        limit: int,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        all_comments: list[dict[str, Any]] = []
        next_cursor: int | str = 0
        api = "https://api.bilibili.com/x/v2/reply/main"
        # Cap total page hits at 20; B站 hot-list realistically tops out
        # well before this, so a runaway pagination loop means risk
        # control is silently truncating.
        for _ in range(20):
            if len(all_comments) >= limit:
                break
            # Cancel check —— 每翻一页都查一次，pacer 可能 sleep 秒级，期间
            # 用户点停止应该立刻退（不是再下载一页才退）。
            maybe_cancel(cancel_token)
            self._pacer.wait()
            try:
                resp = session.get(
                    api,
                    params={
                        "oid": aid,
                        "type": 1,
                        "mode": mode,
                        "next": next_cursor,
                        "ps": 20,
                    },
                    timeout=20,
                )
            except Exception as e:
                return all_comments, False, f"request raised: {e}"

            if resp.status_code != 200:
                return all_comments, False, f"HTTP {resp.status_code}"
            if resp.text.strip().startswith("<"):
                return all_comments, False, "412 risk control (HTML response)"
            try:
                data = resp.json()
            except Exception:
                return all_comments, False, "non-JSON response"
            if data.get("code") != 0:
                return all_comments, False, f"API error: {data.get('message')}"

            body = data.get("data", {}) or {}

            # First page: pinned comment + hot picks (mode=3 only)
            if next_cursor in (0, "0"):
                top = (body.get("upper") or {}).get("top")
                if top:
                    self._append_comment(all_comments, top, limit)
                if mode == 3:
                    for hot in (body.get("hots") or []):
                        if not self._append_comment(all_comments, hot, limit):
                            break

            for reply in body.get("replies") or []:
                if not self._append_comment(all_comments, reply, limit):
                    break

            report_progress(progress_cb, len(all_comments), limit)
            cursor = body.get("cursor") or {}
            if cursor.get("is_end"):
                break
            next_cursor = cursor.get("next") or 0
            if not next_cursor:
                break
        return all_comments, True, None

    @staticmethod
    def _append_comment(
        bucket: list[dict[str, Any]],
        reply: dict[str, Any],
        limit: int,
    ) -> bool:
        """Append one B站 reply to ``bucket``, deduping by text. Returns
        False once the bucket has hit ``limit``."""
        if len(bucket) >= limit:
            return False
        content = (reply.get("content") or {}).get("message", "")
        if not content:
            return True  # skip empty, but keep iterating
        if any(c["text"] == content for c in bucket):
            return True
        bucket.append({
            "rank": len(bucket) + 1,
            "text": content,
            "author": (reply.get("member") or {}).get("uname", ""),
            "likes": int(reply.get("like") or 0),
        })
        return True

    # ── URL parsing ────────────────────────────────────────────────────────
    @staticmethod
    def _extract_video_id(url: str) -> tuple[str, str] | None:
        m = _BV_RE.search(url)
        if m:
            return m.group(1), "bvid"
        m = _AV_RE.search(url)
        if m:
            return m.group(1), "avid"
        return None


ADAPTER = BilibiliCommentAdapter()
