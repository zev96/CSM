"""Zhihu question rank monitor.

Strategy: a two-track fetch. The fast path uses ``curl_cffi`` against
Zhihu's public answers feed (``/api/v4/questions/{id}/answers``) — that
endpoint serves JSON without login for most public questions, and the
``impersonate="chrome120"`` flag in curl_cffi forges the TLS handshake
fingerprint Zhihu's CDN uses to weed out plain ``requests`` traffic.
When the fast path returns 4xx / risk-control HTML, we fall back to
``DrissionPage`` rendering the question page in a real Chromium and
scraping the DOM. The fallback is slow (5–10s per call) but resilient
to most cookie-only blocks.

The rank we report is 1-based: 1 = the user's brand keyword appears in
the top answer, ``-1`` = not found within the configured ``top_n``.
``metric`` carries the snapshot of the inspected answers so the UI can
render an at-a-glance Top-N preview without re-fetching.
"""
from __future__ import annotations
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask
from ..rate_limit import get_pacer, get_breaker
from ..drivers import drission_pool
from ..drivers.cookie_store import CookieStore

logger = logging.getLogger(__name__)


# Pulled from Case-6's UA pool — same browsers it had verified to be
# accepted, dropping the obviously stale (Chrome 90 era) entries.
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


_QUESTION_ID_RE = re.compile(r"/question/(\d+)")
_API_TEMPLATE = "https://www.zhihu.com/api/v4/questions/{qid}/answers"


def _extract_question_id(url: str) -> str | None:
    m = _QUESTION_ID_RE.search(url)
    return m.group(1) if m else None


class ZhihuQuestionAdapter:
    """Implements :class:`BaseMonitorAdapter` for Zhihu question rank."""

    platform: str = "zhihu_question"

    def __init__(self) -> None:
        self._cookies = CookieStore(self.platform)
        self._ua_idx = 0
        self._pacer = get_pacer(self.platform)
        self._breaker = get_breaker(self.platform)

    # ── Public API ──────────────────────────────────────────────────────────
    def fetch(self, task: MonitorTask) -> MonitorResult:
        if not self._breaker.allow():
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="risk_control",
                rank=-1,
                error_message="circuit breaker open for zhihu_question",
            )

        qid = _extract_question_id(task.target_url)
        if not qid:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message=f"could not parse question id from {task.target_url}",
            )

        target_brand = (task.config.get("target_brand") or "").strip()
        top_n = int(task.config.get("top_n") or 10)
        if not target_brand:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="task.config.target_brand is required",
            )

        # Honor the configured request spacing before issuing any HTTP.
        self._pacer.wait()

        # Fast path → fallback chain. On both success and final failure
        # we update the breaker so it can decide whether to open.
        answers, source = self._fetch_fast(qid)
        if answers is None:
            answers, source = self._fetch_browser(task.target_url, qid)
        if answers is None:
            self._breaker.record_failure()
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="both fast and browser fetch failed",
                metric={"source": source},
            )

        self._breaker.record_success()
        rank, snapshot = self._rank_brand(answers, target_brand, top_n)
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="ok",
            rank=rank,
            metric={
                "source": source,
                "target_brand": target_brand,
                "top_n": top_n,
                "answers": snapshot,
                "question_id": qid,
            },
        )

    # ── Fast path: curl_cffi ───────────────────────────────────────────────
    def _fetch_fast(self, qid: str) -> tuple[list[dict[str, Any]] | None, str]:
        try:
            from curl_cffi import requests as cc_requests
        except ImportError:
            logger.warning("curl_cffi not available; skipping fast path")
            return None, "curl_cffi_missing"

        cred = self._cookies.pick()
        ua = cred.user_agent if cred and cred.user_agent else self._next_ua()
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://www.zhihu.com/question/{qid}",
            "x-requested-with": "fetch",
        }
        cookies = self._parse_cookies(cred.cookies_text) if cred else {}

        # ``include`` whitelist trimmed to fields we actually display —
        # matches what the official web client requests, so the API is
        # less likely to flag the request as scripted.
        params = {
            "include": (
                "data[*].is_normal,suggest_edit,comment_count,collapsed_counts,"
                "reviewing_comments_count,can_comment,content,voteup_count,"
                "reshipment_settings,comment_permission,created_time,updated_time,"
                "review_info,question,excerpt,is_labeled,paid_info,relationship.is_authorized,"
                "is_author,voting,is_thanked,is_nothelp,is_recognized;"
                "data[*].author.badge[?(type=best_answerer)].topics;"
                "data[*].author.member.role,member.url_token,member.id,member.name,"
                "member.avatar_url,member.headline,member.gender,member.user_type"
            ),
            "limit": "20",
            "offset": "0",
            "platform": "desktop",
            "sort_by": "default",
        }
        url = _API_TEMPLATE.format(qid=qid)
        try:
            resp = cc_requests.get(
                url,
                headers=headers,
                cookies=cookies,
                params=params,
                impersonate="chrome120",
                timeout=20,
            )
        except Exception as e:
            logger.info("zhihu fast path raised: %s", e)
            if cred:
                self._cookies.mark_failed(cred)
            return None, "curl_cffi_exception"

        if resp.status_code != 200:
            logger.info("zhihu fast path HTTP %s", resp.status_code)
            if cred:
                self._cookies.mark_failed(cred)
            return None, f"curl_cffi_http_{resp.status_code}"

        try:
            payload = resp.json()
        except Exception:
            logger.info("zhihu fast path returned non-JSON (likely risk-control HTML)")
            if cred:
                self._cookies.mark_failed(cred)
            return None, "curl_cffi_non_json"

        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            return None, "curl_cffi_empty_data"

        if cred:
            self._cookies.mark_ok(cred)
        # Map to the simplified shape we use downstream so the rest of
        # the adapter doesn't care which source produced the answers.
        answers: list[dict[str, Any]] = []
        for item in data:
            try:
                author = (item.get("author") or {}).get("name", "")
                content = self._strip_tags(item.get("content") or item.get("excerpt") or "")
                answers.append({
                    "author": author,
                    "content": content[:500],
                    "voteup_count": int(item.get("voteup_count") or 0),
                    "comment_count": int(item.get("comment_count") or 0),
                    "url": item.get("url") or "",
                    "created_time": item.get("created_time"),
                })
            except Exception:
                continue
        return answers, "curl_cffi"

    # ── Fallback: DrissionPage ─────────────────────────────────────────────
    def _fetch_browser(self, url: str, qid: str) -> tuple[list[dict[str, Any]] | None, str]:
        try:
            page = drission_pool.get_page()
        except RuntimeError as e:
            logger.warning("zhihu browser fallback unavailable: %s", e)
            return None, "browser_unavailable"

        try:
            page.get(url)
            # Wait for at least one answer card to render. We poll
            # rather than fixed-sleep so cold caches don't time us out
            # but warm pages don't waste seconds.
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                if page.eles(".AnswerItem", timeout=0.3):
                    break
                time.sleep(0.5)
            cards = page.eles(".AnswerItem")[:20]
        except Exception as e:
            logger.warning("zhihu browser fetch raised: %s", e)
            return None, "browser_exception"

        if not cards:
            return None, "browser_no_cards"

        answers: list[dict[str, Any]] = []
        for card in cards:
            try:
                author_el = card.ele(".AuthorInfo-name", timeout=0.2)
                content_el = card.ele(".RichContent-inner", timeout=0.2)
                vote_el = card.ele(".VoteButton--up", timeout=0.2)
                author = author_el.text if author_el else ""
                content = content_el.text if content_el else ""
                vote_text = vote_el.text if vote_el else "0"
                answers.append({
                    "author": author,
                    "content": content[:500],
                    "voteup_count": _parse_count(vote_text),
                    "comment_count": 0,
                    "url": "",
                    "created_time": None,
                })
            except Exception:
                continue
        return (answers if answers else None), "browser"

    # ── Helpers ────────────────────────────────────────────────────────────
    def _next_ua(self) -> str:
        ua = _UA_POOL[self._ua_idx % len(_UA_POOL)]
        self._ua_idx += 1
        return ua

    @staticmethod
    def _parse_cookies(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for piece in (text or "").split(";"):
            piece = piece.strip()
            if not piece or "=" not in piece:
                continue
            k, _, v = piece.partition("=")
            out[k.strip()] = v.strip()
        return out

    @staticmethod
    def _strip_tags(html: str) -> str:
        # Lightweight tag stripper — we only need a preview snippet, not
        # faithful Markdown. Avoids pulling bs4 into the hot path.
        return re.sub(r"<[^>]+>", "", html or "").strip()

    @staticmethod
    def _rank_brand(
        answers: list[dict[str, Any]],
        brand: str,
        top_n: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (1-based rank, top-N snapshot). Rank=-1 if absent."""
        brand_lc = brand.lower()
        rank = -1
        snapshot: list[dict[str, Any]] = []
        for i, ans in enumerate(answers[:top_n], start=1):
            content = (ans.get("content") or "").lower()
            author = (ans.get("author") or "").lower()
            hit = brand_lc in content or brand_lc in author
            snapshot.append({
                "rank": i,
                "author": ans.get("author", ""),
                "content_preview": (ans.get("content") or "")[:200],
                "voteup_count": ans.get("voteup_count", 0),
                "matches_brand": hit,
            })
            if hit and rank == -1:
                rank = i
        return rank, snapshot


def _parse_count(text: str) -> int:
    """Zhihu shows '1.2 万' / '12.3K' on the rendered page; normalize."""
    if not text:
        return 0
    text = text.replace(",", "").strip()
    try:
        if "万" in text:
            return int(float(text.replace("万", "").strip()) * 10000)
        if "k" in text.lower():
            return int(float(text.lower().replace("k", "").strip()) * 1000)
        m = re.search(r"\d+", text)
        return int(m.group()) if m else 0
    except (ValueError, AttributeError):
        return 0


# Module-level singleton — imported by csm_core/monitor/platforms/__init__.py
ADAPTER = ZhihuQuestionAdapter()
