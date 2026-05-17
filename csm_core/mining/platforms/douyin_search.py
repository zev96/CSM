"""抖音 search adapter — XHR intercept on /aweme/v1/web/general/search/single/.

Highest-risk platform: X-Bogus signature, strict login enforcement,
captcha on first load when fingerprint looks fresh. Strategy:

1. Verify login cookie (sessionid) exists in profile.
2. Navigate search URL; let the React app issue its own (signed) XHR.
3. Listen on page.on('response') for the search endpoint; parse JSON.
4. Scroll to trigger more pages; cap at N scrolls / target_count.
5. Detect captcha/login walls and bail with needs_login or risk_control.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import quote

from csm_core.browser_infra import mining_browser
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import OnCard, OnProgress

logger = logging.getLogger(__name__)


class DouyinSearchAdapter:
    platform: Platform = "douyin"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome:
        if not mining_browser.has_login_cookie("douyin"):
            on_progress(ProgressUpdate(platform=self.platform, phase="needs_login", got=0, target=target_count))
            return SearchOutcome(
                platform=self.platform, status="needs_login", cards_emitted=0,
                error_message="no sessionid in douyin profile",
            )

        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        emitted = 0
        seen: set[str] = set()
        risk_detected = False

        with mining_browser.launched_page("douyin") as page:
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            def _on_response(response: Any) -> None:
                nonlocal emitted, risk_detected
                if cancel_event.is_set() or emitted >= target_count:
                    return
                if "/aweme/v1/web/general/search/single" not in response.url:
                    return
                try:
                    body = response.json()
                except Exception:
                    return
                if body.get("status_code") not in (0, None):
                    return
                for c in self._extract_cards(body):
                    if emitted >= target_count:
                        return
                    if c.platform_video_id in seen:
                        continue
                    seen.add(c.platform_video_id)
                    emitted += 1
                    c.rank_in_search = emitted
                    on_card(c)
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling",
                    got=emitted, target=target_count,
                ))

            page.on("response", _on_response)
            url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            for _ in range(30):
                if cancel_event.is_set() or emitted >= target_count:
                    break
                if _is_captcha_or_login(page):
                    risk_detected = True
                    break
                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(2.0)

        if risk_detected:
            return SearchOutcome(
                platform=self.platform, status="risk_control",
                cards_emitted=emitted, error_message="captcha/login wall",
            )
        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _extract_cards(self, body: dict[str, Any]) -> list[VideoCard]:
        if not isinstance(body, dict):
            return []
        cards: list[VideoCard] = []
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            info = item.get("aweme_info") or {}
            aweme_id = info.get("aweme_id")
            if not aweme_id:
                continue
            author = info.get("author") or {}
            stats = info.get("statistics") or {}
            video = info.get("video") or {}
            cover_list = (video.get("cover") or {}).get("url_list") or []
            duration_ms = video.get("duration") or 0
            cards.append(VideoCard(
                platform="douyin",
                platform_video_id=str(aweme_id),
                url=info.get("share_url") or f"https://www.douyin.com/video/{aweme_id}",
                title=info.get("desc", "") or "",
                author_name=author.get("nickname", "") or "",
                author_id=str(author.get("uid", "")) or "",
                cover_url=cover_list[0] if cover_list else "",
                duration_sec=int(duration_ms / 1000) if duration_ms else None,
                play_count=stats.get("play_count"),
                like_count=stats.get("digg_count"),
                published_at=_ts_to_iso(info.get("create_time")),
                raw=info,
            ))
        return cards


def _ts_to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _is_captcha_or_login(page: Any) -> bool:
    try:
        url = page.url or ""
    except Exception:
        return False
    if "captcha" in url.lower() or "verify" in url.lower():
        return True
    if url.startswith("https://www.douyin.com/passport/"):
        return True
    return False
