"""快手 search adapter — DOM scrape with infinite scroll."""
from __future__ import annotations

import logging
import re
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
            # KNOWN ISSUE (defer to follow-up spec): kuaishou's SPA
            # fingerprints patchright Chromium and renders search results
            # as a "请登录" wall even when monitor.db cookies are injected.
            # Comment API (what monitor uses) works fine; search page does
            # not. Adapter still walks through the motions so partial_done
            # remains a valid outcome.
            url = f"https://www.kuaishou.com/search/video?searchKey={quote(keyword)}"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2.0)
            try:
                # Old debug surface, kept minimal: log title + anchor count
                # so future debugging has a quick signal.
                logger.info(
                    "kuaishou search page: url=%s title=%s",
                    page.url, page.title()[:80],
                )
                anchor_count = page.evaluate(
                    "() => document.querySelectorAll('a[href*=\"/short-video/\"]').length"
                )
                logger.info("kuaishou short-video anchor count: %d", anchor_count)
            except Exception as e:
                logger.warning("kuaishou page introspection failed: %s", e)
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            stagnant_scrolls = 0
            for scroll_n in range(50):
                if cancel_event.is_set() or emitted >= target_count:
                    break
                if _looks_like_captcha(page):
                    return SearchOutcome(
                        platform=self.platform, status="risk_control",
                        cards_emitted=emitted, error_message="captcha intercepted",
                    )

                try:
                    raw_cards = page.evaluate(_EXTRACT_JS)
                except Exception as e:
                    logger.warning("kuaishou evaluate raised: %s", e)
                    raw_cards = []

                new_this_round = 0
                for raw in raw_cards or []:
                    if cancel_event.is_set() or emitted >= target_count:
                        break
                    pid = raw.get("photo_id")
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    emitted += 1
                    new_this_round += 1
                    on_card(VideoCard(
                        platform="kuaishou",
                        platform_video_id=pid,
                        url=raw.get("url") or f"https://www.kuaishou.com/short-video/{pid}",
                        title=(raw.get("title") or "").strip(),
                        author_name=(raw.get("author") or "").strip(),
                        cover_url=raw.get("cover") or "",
                        duration_sec=parse_duration(raw.get("duration_text") or ""),
                        play_count=parse_int_count(raw.get("play_text")),
                        like_count=parse_int_count(raw.get("like_text")),
                        raw=raw,
                        rank_in_search=emitted,
                    ))
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling",
                    got=emitted, target=target_count,
                ))
                logger.info(
                    "[ks-debug] scroll #%d: new=%d  emitted=%d  total_anchors_seen=%d",
                    scroll_n, new_this_round, emitted, len(raw_cards or []),
                )

                if new_this_round == 0:
                    stagnant_scrolls += 1
                    if stagnant_scrolls >= 3:
                        break
                else:
                    stagnant_scrolls = 0

                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(1.5)

            # DOM fallback (Layer 5a): page.evaluate(_EXTRACT_JS) returned nothing,
            # likely due to SPA fingerprint detection (see KNOWN ISSUE comment above).
            # Reuse the same page and fall back to Playwright locator-based DOM scrape.
            # Only fires when the JS-eval path produced nothing; never overrides results.
            # Note: no `risk_detected` guard here — kuaishou's captcha detection
            # short-circuits via early `return` from the with block above (see
            # _looks_like_captcha), so by definition we only reach this fallback
            # path when no captcha was hit.
            # Pass the evaluate path's `seen` set so any late evaluate calls that
            # Playwright drains during DOM scrape don't re-emit the same photo_id.
            if emitted == 0 and not cancel_event.is_set():
                logger.info(
                    "kuaishou_search: evaluate returned 0 items, falling back to DOM scrape"
                )
                dom_cards = self._scrape_dom(page, target_count, on_card, seen=seen)
                emitted += len(dom_cards)

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _scrape_dom(
        self,
        page: Any,
        target_count: int,
        on_card: Any,
        *,
        seen: set[str] | None = None,
    ) -> list[VideoCard]:
        """Fallback: scrape video cards from Kuaishou search page via Playwright locators.

        Kuaishou search SPA has known fingerprint-based bot detection — this fallback
        uses page.locator() instead of page.evaluate(_EXTRACT_JS). Loses precise
        play/like counts (DOM doesn't expose them) but bypasses fingerprint blocks.

        seen: optional pre-populated dedup set (passed from evaluate path to share state).
        Late evaluate results arriving during DOM scrape won't cause double-emission
        if the evaluate path's `seen` set is shared here.
        """
        if seen is None:
            seen = set()
        items: list[VideoCard] = []
        try:
            anchors = page.locator('a[href*="/short-video/"]').all()
        except Exception as e:
            logger.warning("kuaishou_search: DOM locator query failed: %s", e)
            return items

        for loc in anchors:
            if len(items) >= target_count:
                break
            try:
                href = loc.get_attribute("href") or ""
                if not href:
                    continue
                photo_id = _extract_photo_id(href)
                if not photo_id or photo_id in seen:
                    continue
                seen.add(photo_id)

                title = (loc.text_content() or "").strip()[:200]
                url = href if href.startswith("http") else f"https://www.kuaishou.com{href}"

                card = VideoCard(
                    platform="kuaishou",
                    platform_video_id=photo_id,
                    url=url,
                    title=title,
                )
                items.append(card)
                try:
                    on_card(card)
                except Exception:
                    pass
            except Exception as e:
                logger.debug("kuaishou_search: skip DOM locator: %s", e)
                continue

        logger.info("kuaishou_search: DOM fallback yielded %d cards", len(items))
        return items

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
            pid = item.get("data-photo-id") or _extract_photo_id(item.get("href", ""))
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
            pid = item.get("data-photo-id") or _extract_photo_id(item.get("href", ""))
            if not pid or pid in exclude_ids:
                continue
            def _t(sel: str) -> str:
                el = item.select_one(sel)
                return (el.get_text(strip=True) if el else "")
            def _attr(sel: str, key: str) -> str:
                el = item.select_one(sel)
                return (el.get(key, "") if el else "")
            title = _t(".photo-title")
            author = _t(".author-name")
            play_txt = _t(".photo-play-count")
            like_txt = _t(".photo-like-count")
            dur_txt = _t(".photo-duration")
            cards.append(VideoCard(
                platform="kuaishou",
                platform_video_id=pid,
                url=f"https://www.kuaishou.com/short-video/{pid}",
                title=title,
                author_name=author,
                cover_url=_attr("img.photo-cover", "src"),
                duration_sec=parse_duration(dur_txt),
                play_count=parse_int_count(play_txt),
                like_count=parse_int_count(like_txt),
                raw={"title": title, "author": author, "play_txt": play_txt, "like_txt": like_txt},
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


_PHOTO_ID_RE = re.compile(r"/short-video/([A-Za-z0-9_-]+)")


def _extract_photo_id(href: str) -> str:
    """Extract Kuaishou photo ID from href like '/short-video/3xabc123'.

    Accepts hyphens and underscores in addition to alphanumerics — real Kuaishou
    photo IDs include hyphens (e.g. "3xa1b2c-def-456"). Regex matches _EXTRACT_JS
    and storage.py _VIDEO_ID_PATTERNS so all code paths agree on platform_video_id.
    """
    m = _PHOTO_ID_RE.search(href or "")
    return m.group(1) if m else ""


def _looks_like_captcha(page: Any) -> bool:
    try:
        url = page.url or ""
    except Exception:
        return False
    return "/captcha" in url or "verify" in url.lower()


# JS executed in the search page. Walks each /short-video/<id> anchor up
# to a stable card ancestor and pulls metadata from innerText. Same shape
# as bilibili's _EXTRACT_JS (which the test runs verified the heuristic on).
_EXTRACT_JS = r"""
() => {
  const anchors = Array.from(document.querySelectorAll('a[href*="/short-video/"]'));
  const seen = new Set();
  const cards = [];
  for (const a of anchors) {
    const m = a.href.match(/\/short-video\/([0-9a-zA-Z_-]+)/);
    if (!m) continue;
    const pid = m[1];
    if (seen.has(pid)) continue;
    seen.add(pid);
    // Walk up until we find an ancestor with reasonable text content.
    let node = a;
    for (let i = 0; i < 6 && node; i++) {
      if (node.parentElement) node = node.parentElement; else break;
      const txt = (node.innerText || "").trim();
      if (txt.length > 20) break;
    }
    const txt = (node && node.innerText) || a.innerText || "";
    const lines = txt.split("\n").map(s => s.trim()).filter(Boolean);
    let title = "";
    for (const line of lines) {
      if (/^[\d.万亿k]+$/i.test(line)) continue;
      if (/^\d{1,2}:\d{2}$/.test(line)) continue;
      if (line.length > title.length) title = line;
    }
    let dur = "", play = "", like = "", author = "";
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!dur && /^\d{1,2}:\d{2}(:\d{2})?$/.test(line)) dur = line;
      else if (/^[\d.,]+(万|亿|k|m)?$/i.test(line)) {
        if (!play) play = line;
        else if (!like) like = line;
      }
    }
    if (!author && lines.length >= 2) {
      // Heuristic: the author line is usually the second non-numeric line.
      const text_lines = lines.filter(l =>
        !/^[\d.,]+(万|亿|k|m)?$/i.test(l) && !/^\d{1,2}:\d{2}$/.test(l)
      );
      if (text_lines.length >= 2) author = text_lines[1];
    }
    let cover = "";
    if (node && node.querySelector) {
      const img = node.querySelector('img');
      if (img) cover = img.getAttribute("src") || img.getAttribute("data-src") || "";
    }
    cards.push({
      photo_id: pid,
      url: a.href,
      title,
      author,
      duration_text: dur,
      play_text: play,
      like_text: like,
      cover,
      raw_text: txt.slice(0, 300),
    });
  }
  return cards;
}
""".strip()
