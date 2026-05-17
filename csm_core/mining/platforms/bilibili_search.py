"""B 站 search adapter — intercepts the wbi search XHR, falls back to DOM.

Why XHR-first: B 站's React app renders cards lazily, and DOM selectors
break every ~6 months when the search page is rebuilt. The
``/x/web-interface/wbi/search/type`` response is a stable contract — we
just route it from the browser into our card stream.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any
from urllib.parse import quote

from csm_core.browser_infra import mining_browser
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import (
    NeedsLoginError, OnCard, OnProgress, parse_duration, parse_int_count,
)

logger = logging.getLogger(__name__)


class BilibiliSearchAdapter:
    platform: Platform = "bilibili"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome:
        if not mining_browser.has_login_cookie("bilibili"):
            on_progress(ProgressUpdate(platform=self.platform, phase="needs_login", got=0, target=target_count))
            return SearchOutcome(platform=self.platform, status="needs_login", cards_emitted=0,
                                 error_message="no SESSDATA in profile")

        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        emitted = 0
        seen_bvids: set[str] = set()

        with mining_browser.launched_page("bilibili") as page:
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            def _handle_response(response: Any) -> None:
                nonlocal emitted
                if cancel_event.is_set():
                    return
                if "/web-interface/wbi/search/type" not in response.url and \
                   "/web-interface/search/type" not in response.url:
                    return
                try:
                    body = response.json()
                except Exception:
                    return
                cards = self._extract_cards(body)
                for c in cards:
                    if cancel_event.is_set() or emitted >= target_count:
                        return
                    if c.platform_video_id in seen_bvids:
                        continue
                    seen_bvids.add(c.platform_video_id)
                    emitted += 1
                    c.rank_in_search = emitted
                    on_card(c)
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling",
                    got=emitted, target=target_count,
                ))

            page.on("response", _handle_response)
            url = f"https://search.bilibili.com/all?keyword={quote(keyword)}"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # Paginate by clicking "下一页" or by URL ?page=N — URL is more reliable.
            for page_num in range(2, 11):  # initial goto already loaded page 1; cap at ~200 results
                if cancel_event.is_set() or emitted >= target_count:
                    break
                page.goto(
                    f"{url}&page={page_num}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                # Give the XHR a chance to fire before the next page.
                for _ in range(20):
                    if cancel_event.is_set() or emitted >= target_count:
                        break
                    time.sleep(0.5)
                    if emitted >= target_count:
                        break

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _extract_cards(self, body: dict[str, Any]) -> list[VideoCard]:
        """Parse a single wbi search response into VideoCards."""
        if not isinstance(body, dict):
            return []
        if body.get("code") != 0:
            return []
        result = body.get("data", {}).get("result", [])
        cards: list[VideoCard] = []
        for item in result:
            if not isinstance(item, dict) or item.get("type") != "video":
                continue
            bvid = item.get("bvid")
            if not bvid:
                continue
            cards.append(VideoCard(
                platform="bilibili",
                platform_video_id=bvid,
                url=f"https://www.bilibili.com/video/{bvid}",
                title=_strip_em(item.get("title", "")),
                author_name=item.get("author", ""),
                author_id=str(item.get("mid", "")) or "",
                cover_url=_normalize_url(item.get("pic", "")),
                duration_sec=parse_duration(item.get("duration", "")),
                play_count=item.get("play") if isinstance(item.get("play"), int) else parse_int_count(str(item.get("play", ""))),
                like_count=item.get("like") if isinstance(item.get("like"), int) else parse_int_count(str(item.get("like", ""))),
                published_at=_pubdate_to_iso(item.get("pubdate")),
                raw=item,
            ))
        return cards


def _strip_em(text: str) -> str:
    """Search API wraps keyword hits in <em class="keyword">…</em>. Strip."""
    if not text:
        return ""
    # Cheap regex strip — no DOM parser needed.
    import re
    return re.sub(r"</?em[^>]*>", "", text)


def _normalize_url(u: str) -> str:
    if u.startswith("//"):
        return "https:" + u
    return u or ""


def _pubdate_to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None
