"""B 站 search adapter — DOM extraction from the SSR search page.

The original design intercepted ``/x/web-interface/wbi/search/type`` XHR
but **bilibili's search page is server-side rendered as of mid-2026**
— it returns the full HTML on ``page.goto()`` and never fires that XHR.
We extract video metadata from the DOM via ``page.evaluate``, deduping
by BV ID since each card has multiple anchor links to the same video
(cover image + title + author each get their own ``<a href="/video/BV...">``).
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

            base_url = f"https://search.bilibili.com/all?keyword={quote(keyword)}"
            for page_num in range(1, 11):  # cap at 10 pages ≈ 200 results
                if cancel_event.is_set() or emitted >= target_count:
                    break
                target_url = base_url if page_num == 1 else f"{base_url}&page={page_num}"
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
                    time.sleep(2.0)  # let SSR + hydration settle
                except Exception as e:
                    logger.warning("bilibili page %d goto failed: %s", page_num, e)
                    continue

                try:
                    raw_cards = page.evaluate(_EXTRACT_JS)
                except Exception as e:
                    logger.warning("bilibili page %d evaluate failed: %s", page_num, e)
                    continue

                new_this_page = 0
                for raw in raw_cards or []:
                    if cancel_event.is_set() or emitted >= target_count:
                        break
                    bvid = raw.get("bvid")
                    if not bvid or bvid in seen_bvids:
                        continue
                    seen_bvids.add(bvid)
                    emitted += 1
                    new_this_page += 1
                    on_card(VideoCard(
                        platform="bilibili",
                        platform_video_id=bvid,
                        url=raw.get("url") or f"https://www.bilibili.com/video/{bvid}",
                        title=(raw.get("title") or "").strip(),
                        author_name=(raw.get("author") or "").strip(),
                        cover_url=_normalize_url(raw.get("cover") or ""),
                        duration_sec=parse_duration(raw.get("duration_text") or ""),
                        play_count=_parse_count(raw.get("play_text")),
                        like_count=_parse_count(raw.get("like_text")),
                        published_at=(raw.get("pubdate_text") or "").strip() or None,
                        raw=raw,
                        rank_in_search=emitted,
                    ))
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling",
                    got=emitted, target=target_count,
                ))
                # End-of-results heuristic: if a page yielded zero new BVs,
                # we've likely run past the last results page — stop early.
                if new_this_page == 0 and page_num > 1:
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


def _parse_count(text: str | None) -> int | None:
    """Wrapper that handles None + delegates to parse_int_count."""
    if text is None:
        return None
    return parse_int_count(text)


def _strip_em(text: str) -> str:
    """Search API wraps keyword hits in <em class="keyword">…</em>. Strip."""
    if not text:
        return ""
    # Cheap regex strip — no DOM parser needed.
    import re
    return re.sub(r"</?em[^>]*>", "", text)


# JS executed in the search page to extract one card per unique BV id.
# Strategy: for each unique BV link, walk up to a stable ancestor (the
# closest element that ALSO contains a non-link "play count" digit cluster
# or a "duration" stamp) and dump that element's innerText. We then split
# on \n on the Python side. Less fragile than CSS selectors that change
# every B 站 search-page revamp.
_EXTRACT_JS = r"""
() => {
  const anchors = Array.from(document.querySelectorAll('a[href*="/video/BV"]'));
  const seen = new Set();
  const cards = [];
  for (const a of anchors) {
    const m = a.href.match(/\/video\/(BV[A-Za-z0-9]+)/);
    if (!m) continue;
    const bvid = m[1];
    if (seen.has(bvid)) continue;
    seen.add(bvid);
    // Walk up until we find an ancestor with reasonable text content.
    let node = a;
    for (let i = 0; i < 6 && node; i++) {
      if (node.parentElement) node = node.parentElement; else break;
      const txt = (node.innerText || "").trim();
      if (txt.length > 30) break;
    }
    const txt = (node && node.innerText) || a.innerText || "";
    const lines = txt.split("\n").map(s => s.trim()).filter(Boolean);
    // Heuristic: title is the longest line that's not a number-only token.
    let title = "";
    for (const line of lines) {
      if (/^[\d.万亿k]+$/i.test(line)) continue;
      if (line.length > title.length) title = line;
    }
    // Find author: a sibling <a> with no /video/ in href, or any line
    // following a 时长 token (mm:ss). Cheap heuristic — pick the line
    // right after the duration line, which is conventionally the uploader.
    let author = "";
    for (let i = 0; i < lines.length - 1; i++) {
      if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(lines[i])) {
        author = lines[i + 1] || "";
        break;
      }
    }
    // Duration + play count: regex over lines.
    let dur = "", play = "", pub = "";
    for (const line of lines) {
      if (!dur && /^\d{1,2}:\d{2}(:\d{2})?$/.test(line)) dur = line;
      else if (!play && /^[\d.,]+(万|亿|k|m)?$/i.test(line)) play = line;
      else if (!pub && /^(·|\s)*(\d{4}-\d{2}-\d{2}|昨天|前天|今天|\d+(天|月|周|小时|分钟)前|\d{2}-\d{2})/i.test(line)) {
        pub = line.replace(/^[·\s]+/, "");
      }
    }
    // Cover image: try to find an <img> within the card subtree.
    let cover = "";
    if (node && node.querySelector) {
      const img = node.querySelector('img[src*="hdslb.com"], img[data-src*="hdslb.com"], img');
      if (img) cover = img.getAttribute("src") || img.getAttribute("data-src") || "";
    }
    cards.push({
      bvid,
      url: a.href,
      title,
      author,
      duration_text: dur,
      play_text: play,
      pubdate_text: pub,
      cover,
      raw_text: txt.slice(0, 300),
    });
  }
  return cards;
}
""".strip()


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
