"""快手 search adapter — DOM scrape with infinite scroll."""
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
from csm_core.mining.platforms._common import (
    OnCard, OnProgress, RiskControlError,
    parse_duration, parse_int_count,
)

logger = logging.getLogger(__name__)


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
            on_progress(ProgressUpdate(platform=self.platform, phase="needs_login", got=0, target=target_count))
            return SearchOutcome(platform=self.platform, status="needs_login", cards_emitted=0)

        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        emitted = 0
        seen: set[str] = set()

        with mining_browser.launched_page("kuaishou") as page:
            url = f"https://www.kuaishou.com/search/video?searchKey={quote(keyword)}"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            stagnant_scrolls = 0
            for _ in range(50):  # safety cap on scrolls
                if cancel_event.is_set() or emitted >= target_count:
                    break

                if _looks_like_captcha(page):
                    return SearchOutcome(
                        platform=self.platform, status="risk_control",
                        cards_emitted=emitted, error_message="captcha intercepted",
                    )

                html = page.content()
                new_cards = self._extract_from_dom(html, exclude_ids=seen)
                if new_cards:
                    stagnant_scrolls = 0
                    for c in new_cards:
                        if emitted >= target_count:
                            break
                        seen.add(c.platform_video_id)
                        emitted += 1
                        c.rank_in_search = emitted
                        on_card(c)
                    on_progress(ProgressUpdate(
                        platform=self.platform, phase="scrolling",
                        got=emitted, target=target_count,
                    ))
                else:
                    stagnant_scrolls += 1
                    if stagnant_scrolls >= 3:
                        break  # end of results

                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(1.5)

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _extract_from_dom(self, html: str, *, exclude_ids: set[str]) -> list[VideoCard]:
        """Parse Kuaishou search DOM into cards. Uses lxml for speed."""
        try:
            from lxml import html as lxml_html
        except ImportError:
            # Fallback to BeautifulSoup if lxml missing — slower but tolerable.
            return self._extract_via_bs4(html, exclude_ids)

        tree = lxml_html.fromstring(html)
        cards: list[VideoCard] = []
        for item in tree.cssselect("a.search-result-item"):
            pid = item.get("data-photo-id") or _href_to_photo_id(item.get("href", ""))
            if not pid or pid in exclude_ids:
                continue
            title = _first_text(item.cssselect(".photo-title"))
            author = _first_text(item.cssselect(".author-name"))
            play_txt = _first_text(item.cssselect(".photo-play-count"))
            like_txt = _first_text(item.cssselect(".photo-like-count"))
            dur_txt = _first_text(item.cssselect(".photo-duration"))
            cover = _first_attr(item.cssselect("img.photo-cover"), "src")
            cards.append(VideoCard(
                platform="kuaishou",
                platform_video_id=pid,
                url=f"https://www.kuaishou.com/short-video/{pid}",
                title=title,
                author_name=author,
                cover_url=cover,
                duration_sec=parse_duration(dur_txt),
                play_count=parse_int_count(play_txt),
                like_count=parse_int_count(like_txt),
                raw={"title": title, "author": author, "play_txt": play_txt, "like_txt": like_txt},
            ))
        return cards

    def _extract_via_bs4(self, html: str, exclude_ids: set[str]) -> list[VideoCard]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cards: list[VideoCard] = []
        for item in soup.select("a.search-result-item"):
            pid = item.get("data-photo-id") or _href_to_photo_id(item.get("href", ""))
            if not pid or pid in exclude_ids:
                continue
            def _t(sel: str) -> str:
                el = item.select_one(sel)
                return (el.get_text(strip=True) if el else "")
            def _attr(sel: str, key: str) -> str:
                el = item.select_one(sel)
                return (el.get(key, "") if el else "")
            cards.append(VideoCard(
                platform="kuaishou",
                platform_video_id=pid,
                url=f"https://www.kuaishou.com/short-video/{pid}",
                title=_t(".photo-title"),
                author_name=_t(".author-name"),
                cover_url=_attr("img.photo-cover", "src"),
                duration_sec=parse_duration(_t(".photo-duration")),
                play_count=parse_int_count(_t(".photo-play-count")),
                like_count=parse_int_count(_t(".photo-like-count")),
                raw={},
            ))
        return cards


def _first_text(els: list[Any]) -> str:
    if not els:
        return ""
    return (els[0].text_content() or "").strip()


def _first_attr(els: list[Any], attr: str) -> str:
    if not els:
        return ""
    return els[0].get(attr, "") or ""


def _href_to_photo_id(href: str) -> str:
    if not href:
        return ""
    import re
    m = re.search(r"/short-video/([0-9a-zA-Z]+)", href)
    return m.group(1) if m else ""


def _looks_like_captcha(page: Any) -> bool:
    try:
        url = page.url or ""
    except Exception:
        return False
    return "/captcha" in url or "verify" in url.lower()
