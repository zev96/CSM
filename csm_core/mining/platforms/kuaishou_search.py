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
            # Track every response so we can see what the SSO redirect chain
            # is doing (id.kuaishou.com → www.kuaishou.com → session cookie).
            seen_urls: list[str] = []
            def _on_response(resp: Any) -> None:
                if "kuaishou.com" in resp.url:
                    seen_urls.append(f"{resp.status} {resp.url[:160]}")
            page.on("response", _on_response)

            # Step 1: visit id.kuaishou.com directly — that's where passToken
            # was set; touching this domain triggers the SSO handshake.
            try:
                logger.info("[ks-debug] warm-up A: id.kuaishou.com")
                page.goto("https://id.kuaishou.com/", wait_until="networkidle", timeout=20_000)
                time.sleep(2.0)
            except Exception as e:
                logger.warning("[ks-debug] id warm-up failed: %s", e)

            # Step 2: visit www homepage with networkidle so all redirects
            # and the session-cookie XHR complete before we move on.
            try:
                logger.info("[ks-debug] warm-up B: www.kuaishou.com (networkidle)")
                page.goto("https://www.kuaishou.com/", wait_until="networkidle", timeout=30_000)
                time.sleep(4.0)
            except Exception as e:
                logger.warning("[ks-debug] homepage warm-up failed: %s", e)

            # Dump cookies + responses after warm-ups so we can confirm
            # whether session cookies got set.
            try:
                cookies_now = page.context.cookies("https://www.kuaishou.com/")
                cookie_names = sorted({c["name"] for c in cookies_now})
                logger.info("[ks-debug] cookies on www after warmup: %s", cookie_names)
            except Exception as e:
                logger.warning("[ks-debug] cookies introspection failed: %s", e)
            logger.info("[ks-debug] %d responses recorded during warm-up", len(seen_urls))
            for u in seen_urls[-20:]:
                logger.info("[ks-debug]   resp: %s", u)
            seen_urls.clear()

            url = f"https://www.kuaishou.com/search/video?searchKey={quote(keyword)}"
            logger.info("[ks-debug] goto search %s", url)
            page.goto(url, wait_until="networkidle", timeout=30_000)
            time.sleep(3.0)
            try:
                logger.info(
                    "[ks-debug] after goto: url=%s title=%s",
                    page.url, page.title()[:80],
                )
                # Inventory all anchor URL patterns to discover the real route.
                hrefs_summary = page.evaluate(r"""
() => {
  const links = Array.from(document.querySelectorAll('a[href]'));
  const buckets = {};
  for (const a of links) {
    const h = a.getAttribute('href') || '';
    // Normalize: keep only the path prefix segments
    const m = h.match(/^([a-z]+:)?\/\/[^/]*(\/[^?#]*)/) || [null,null,h];
    const path = (m[2] || h).split('/').slice(0,4).join('/');
    buckets[path] = (buckets[path] || 0) + 1;
  }
  return Object.entries(buckets).sort((a,b) => b[1]-a[1]).slice(0,15);
}
""")
                logger.info("[ks-debug] top anchor path prefixes: %s", hrefs_summary)
                body_preview = page.evaluate(
                    "() => (document.body.innerText || '').slice(0, 600)"
                )
                logger.info("[ks-debug] body[:600]=%r", body_preview)
                # Dump full anchor hrefs (not just prefix bucketing) + look
                # for clickable cards that aren't anchors.
                full_hrefs = page.evaluate(r"""
() => {
  const a = Array.from(document.querySelectorAll('a[href]')).map(x => x.getAttribute('href'));
  const clickableDivs = Array.from(document.querySelectorAll('[data-photo-id], [data-id*="photo"], [data-photo], [role="link"]'))
    .slice(0, 10).map(x => ({
      tag: x.tagName, role: x.getAttribute('role'),
      'data-photo-id': x.getAttribute('data-photo-id'),
      'data-id': x.getAttribute('data-id'),
      'data-photo': x.getAttribute('data-photo'),
    }));
  return { anchors: a, clickableDivs };
}
""")
                logger.info("[ks-debug] ALL anchor hrefs (%d): %s", len(full_hrefs['anchors']), full_hrefs['anchors'][:40])
                logger.info("[ks-debug] clickable divs: %s", full_hrefs['clickableDivs'])
            except Exception as e:
                logger.warning("[ks-debug] page introspection failed: %s", e)
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
