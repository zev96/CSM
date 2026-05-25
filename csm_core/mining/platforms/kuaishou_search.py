"""快手 search adapter — GraphQL POST against /graphql.

Strategy: use Patchright only to ESTABLISH the login session (Kuaishou's
auth cookies land in the BrowserContext via ``_inject_monitor_cookies`` +
``page.goto``). Then extract the cookies into an httpx Client and POST the
``visionSearchPhoto`` GraphQL operation directly — bypassing the SPA,
which fingerprints Patchright Chromium and renders a "请登录" wall.

Mirrors MediaCrawler kuaishou/client.py:200-209 (visionSearchPhoto
post_data shape) and kuaishou/client.py:142-145 (cookie extraction).

The GraphQL query template is vendored at
``csm_core/mining/platforms/_vendor/mc_kuaishou_search.graphql`` — see
``_vendor/README.md`` for the NCL 1.1 license attribution and
FEASIBILITY_ANALYSIS.md §1.2 / §2 阶段 3 for the design notes.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from csm_core.browser_infra import mining_browser, rate_limit
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms import _http, _risk
from csm_core.mining.platforms._common import OnCard, OnProgress

logger = logging.getLogger(__name__)


_GRAPHQL_ENDPOINT = "https://www.kuaishou.com/graphql"
_BOOTSTRAP_URL = "https://www.kuaishou.com"
_REFERER = "https://www.kuaishou.com/search/video"
_COOKIE_URLS = ["https://www.kuaishou.com", "https://id.kuaishou.com"]
_QUERY_TEMPLATE_PATH = (
    Path(__file__).parent / "_vendor" / "mc_kuaishou_search.graphql"
)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class KuaishouSearchAdapter:
    platform: Platform = "kuaishou"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome:
        if not mining_browser.has_login_cookie("kuaishou"):
            on_progress(ProgressUpdate(
                platform=self.platform, phase="needs_login",
                got=0, target=target_count,
            ))
            return SearchOutcome(
                platform=self.platform, status="needs_login", cards_emitted=0,
            )

        on_progress(ProgressUpdate(
            platform=self.platform, phase="launching",
            got=0, target=target_count,
        ))

        try:
            query = _QUERY_TEMPLATE_PATH.read_text(encoding="utf-8")
        except OSError as e:
            logger.exception("kuaishou: missing vendored GraphQL template: %s", e)
            return SearchOutcome(
                platform=self.platform, status="failed", cards_emitted=0,
                error_message="vendored graphql template missing",
            )

        emitted = 0
        seen: set[str] = set()
        pacer = rate_limit.get_pacer("kuaishou")
        breaker = rate_limit.get_breaker("kuaishou")

        with mining_browser.launched_page("kuaishou") as page:
            try:
                page.goto(
                    _BOOTSTRAP_URL,
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
            except Exception as e:
                logger.warning("kuaishou bootstrap goto failed: %s", e)
                return SearchOutcome(
                    platform=self.platform, status="failed",
                    cards_emitted=0, error_message=f"bootstrap failed: {e}",
                )

            if _risk.detect(page):
                return SearchOutcome(
                    platform=self.platform, status="risk_control",
                    cards_emitted=0, error_message="captcha at bootstrap",
                )

            try:
                cookies_str, _ = _http.cookies_from_context(
                    page.context, urls=_COOKIE_URLS,
                )
            except Exception as e:
                logger.exception("kuaishou cookies_from_context failed: %s", e)
                return SearchOutcome(
                    platform=self.platform, status="failed",
                    cards_emitted=0, error_message=f"cookie extraction failed: {e}",
                )
            if not cookies_str:
                return SearchOutcome(
                    platform=self.platform, status="needs_login",
                    cards_emitted=0, error_message="no cookies in context",
                )

            try:
                ua = page.evaluate("navigator.userAgent") or _DEFAULT_UA
            except Exception:
                ua = _DEFAULT_UA

            on_progress(ProgressUpdate(
                platform=self.platform, phase="scrolling",
                got=0, target=target_count,
            ))

            # v0.5.7: switched from build_httpx_client to build_stealth_client.
            # Server returned 200 + empty feeds + pcursor='no_more' under vanilla
            # httpx — JA3 fingerprint shadow-ban. curl_cffi impersonate='chrome120'
            # forges the TLS handshake so 快手 treats it as a real Chrome.
            with _http.build_stealth_client(
                cookies_str=cookies_str,
                user_agent=ua,
                referer=_REFERER,
                extra_headers={
                    "Content-Type": "application/json",
                    "Origin": "https://www.kuaishou.com",
                },
            ) as client:
                pcursor = ""
                search_session_id = ""
                page_index = 0

                while emitted < target_count and not cancel_event.is_set():
                    if page_index > 0:
                        # Honor 5-15s jitter between paginated POSTs.
                        pacer.wait()
                    page_index += 1

                    if not breaker.allow():
                        logger.warning("kuaishou circuit breaker open — pausing")
                        break

                    post_body = {
                        "operationName": "visionSearchPhoto",
                        "variables": {
                            "keyword": keyword,
                            "pcursor": pcursor,
                            "page": "search",
                            "searchSessionId": search_session_id,
                        },
                        "query": query,
                    }
                    # Match MediaCrawler kuaishou/client.py:87 — compact JSON,
                    # raw UTF-8 (no \uXXXX escapes). Some GraphQL gateways
                    # care about exact payload bytes for rate-limit fingerprint.
                    payload = json.dumps(
                        post_body, separators=(",", ":"), ensure_ascii=False,
                    ).encode("utf-8")

                    try:
                        # curl_cffi.Session.post uses ``data=`` (not httpx's
                        # ``content=``); both pass raw bytes through.
                        resp = client.post(_GRAPHQL_ENDPOINT, data=payload)
                    except Exception as e:
                        breaker.record_failure()
                        logger.warning("kuaishou graphql POST raised: %s", e)
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=f"graphql POST failed: {e}",
                        )

                    if resp.status_code in (401, 403):
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="needs_login",
                            cards_emitted=emitted,
                            error_message=(
                                f"graphql {resp.status_code} (session expired)"
                            ),
                        )

                    if resp.status_code in (429, 451, 503):
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="risk_control",
                            cards_emitted=emitted,
                            error_message=f"graphql {resp.status_code}",
                        )

                    if resp.status_code != 200:
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=f"graphql HTTP {resp.status_code}",
                        )

                    try:
                        body = resp.json()
                    except Exception as e:
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=f"graphql non-json: {e}",
                        )

                    data = (body or {}).get("data") or {}
                    vsp = data.get("visionSearchPhoto") or {}
                    if not isinstance(vsp, dict):
                        # cookies invalid / abuse-flagged / wrong domain.
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="needs_login",
                            cards_emitted=emitted,
                            error_message="visionSearchPhoto null (cookies invalid?)",
                        )

                    feeds = vsp.get("feeds") or []
                    search_session_id = (
                        vsp.get("searchSessionId") or search_session_id
                    )
                    new_pcursor = vsp.get("pcursor") or "no_more"

                    new_this_round = 0
                    for feed in feeds:
                        if emitted >= target_count or cancel_event.is_set():
                            break
                        card = self._feed_to_card(feed, rank=emitted + 1)
                        if card is None:
                            continue
                        if card.platform_video_id in seen:
                            continue
                        seen.add(card.platform_video_id)
                        emitted += 1
                        new_this_round += 1
                        on_card(card)

                    on_progress(ProgressUpdate(
                        platform=self.platform, phase="scrolling",
                        got=emitted, target=target_count,
                    ))
                    logger.info(
                        "[ks-graphql] page=%d new=%d emitted=%d pcursor=%r",
                        page_index, new_this_round, emitted, new_pcursor,
                    )

                    breaker.record_success()

                    if new_pcursor == "no_more" or new_this_round == 0:
                        break
                    pcursor = new_pcursor

        if cancel_event.is_set():
            return SearchOutcome(
                platform=self.platform, status="cancelled",
                cards_emitted=emitted,
            )
        on_progress(ProgressUpdate(
            platform=self.platform, phase="done",
            got=emitted, target=target_count,
        ))
        return SearchOutcome(
            platform=self.platform, status="done", cards_emitted=emitted,
        )

    def _feed_to_card(
        self, feed: dict[str, Any], rank: int,
    ) -> VideoCard | None:
        """Convert one ``visionSearchPhoto`` feed entry to a VideoCard.

        Feed shape (per the vendored GraphQL template's ``feedContent``
        fragment): ``{type, author: {id, name, headerUrl}, photo: {id,
        duration, caption, likeCount, viewCount, commentCount, coverUrl,
        timestamp}, ...}``. Duration and timestamp are milliseconds.
        """
        if not isinstance(feed, dict):
            return None
        photo = feed.get("photo") or {}
        pid_raw = photo.get("id")
        if pid_raw is None:
            return None
        pid = str(pid_raw)
        author = feed.get("author") or {}
        author_id = author.get("id")
        duration_ms = photo.get("duration") or 0
        ts_ms = photo.get("timestamp") or 0
        return VideoCard(
            platform="kuaishou",
            platform_video_id=pid,
            url=f"https://www.kuaishou.com/short-video/{pid}",
            title=(
                photo.get("caption")
                or photo.get("originCaption")
                or ""
            ).strip(),
            author_name=(author.get("name") or "").strip(),
            author_id=str(author_id) if author_id is not None else "",
            cover_url=photo.get("coverUrl") or "",
            duration_sec=int(duration_ms / 1000) if duration_ms else None,
            play_count=photo.get("viewCount"),
            like_count=photo.get("likeCount"),
            published_at=_ts_ms_to_iso(ts_ms) if ts_ms else None,
            raw=feed,
            rank_in_search=rank,
        )


def _ts_ms_to_iso(ts_ms: int) -> str | None:
    if not isinstance(ts_ms, (int, float)) or ts_ms <= 0:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(
            ts_ms / 1000.0, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None
