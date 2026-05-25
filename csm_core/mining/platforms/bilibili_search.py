"""B 站 search adapter — WBI-signed call to /x/web-interface/wbi/search/type.

The earlier version scraped the SSR search-page DOM via ``page.evaluate``.
That works for the first page when the SSR layout is stable but breaks
after layout revamps and trips anti-crawl walls past a few pages. The
signed API is what B 站's own search frontend uses for pagination and
isn't fingerprint-gated.

Mirrors MediaCrawler bilibili/client.py:193-218 (search call) and
bilibili/client.py:119-161 (WBI key fetch + signing). WBI signer is
vendored at ``csm_core/mining/platforms/_vendor/mc_bilibili_sign.py``.

See FEASIBILITY_ANALYSIS.md §1.3 / §2 阶段 4.
"""
from __future__ import annotations

import logging
import random
import re
import threading
from typing import Any

from csm_core.browser_infra import mining_browser, rate_limit
from csm_core.mining.config import PAGE_DELAY_RANGE_SEC, get_max_attempts
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms import _http, _risk
from csm_core.mining.platforms._common import (
    OnCard, OnProgress, parse_duration, parse_int_count,
)
from csm_core.mining.platforms._vendor.mc_bilibili_sign import BilibiliSign

logger = logging.getLogger(__name__)


_BOOTSTRAP_URL = "https://www.bilibili.com"
_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
_SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
_REFERER = "https://www.bilibili.com/"
_COOKIE_URLS = ["https://www.bilibili.com", "https://api.bilibili.com"]
_PAGE_SIZE = 20
_PAGE_CAP = 50  # B 站 search type cap is ~50 pages * 20 = 1000 results

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BilibiliSearchAdapter:
    platform: Platform = "bilibili"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
        max_attempts: int | None = None,
    ) -> SearchOutcome:
        if max_attempts is None:
            max_attempts = get_max_attempts("bilibili")

        if not mining_browser.has_login_cookie("bilibili"):
            on_progress(ProgressUpdate(
                platform=self.platform, phase="needs_login",
                got=0, target=target_count,
            ))
            return SearchOutcome(
                platform=self.platform, status="needs_login", cards_emitted=0,
                error_message="no SESSDATA in bilibili profile",
            )

        on_progress(ProgressUpdate(
            platform=self.platform, phase="launching",
            got=0, target=target_count,
        ))

        emitted = 0
        seen_bvids: set[str] = set()
        pacer = rate_limit.get_pacer("bilibili")
        breaker = rate_limit.get_breaker("bilibili")

        with mining_browser.launched_page("bilibili") as page:
            try:
                page.goto(
                    _BOOTSTRAP_URL,
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
            except Exception as e:
                logger.warning("bilibili bootstrap goto failed: %s", e)
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
                logger.exception("bilibili cookies_from_context failed: %s", e)
                return SearchOutcome(
                    platform=self.platform, status="failed",
                    cards_emitted=0,
                    error_message=f"cookie extraction failed: {e}",
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

            with _http.build_httpx_client(
                cookies_str=cookies_str, user_agent=ua, referer=_REFERER,
            ) as client:
                try:
                    img_key, sub_key = self._fetch_wbi_keys(client)
                except Exception as e:
                    logger.warning("bilibili WBI key fetch failed: %s", e)
                    return SearchOutcome(
                        platform=self.platform, status="failed",
                        cards_emitted=0,
                        error_message=f"WBI key fetch failed: {e}",
                    )
                signer = BilibiliSign(img_key, sub_key)

                page_num = 1
                while emitted < target_count and not cancel_event.is_set():
                    if page_num > 1:
                        pacer.wait()

                    if not breaker.allow():
                        logger.warning("bilibili circuit breaker open — pausing")
                        break

                    if page_num > max_attempts:
                        logger.info("[bili] hit max_attempts=%d, stopping", max_attempts)
                        on_progress(ProgressUpdate(
                            platform=self.platform, phase="done",
                            got=emitted, target=target_count,
                            note=f"翻页保护：达到 {max_attempts} 页上限",
                        ))
                        break

                    raw_params: dict[str, Any] = {
                        "search_type": "video",
                        "keyword": keyword,
                        "page": page_num,
                        "page_size": _PAGE_SIZE,
                    }
                    signed = signer.sign(dict(raw_params))

                    try:
                        resp = client.get(_SEARCH_URL, params=signed)
                    except Exception as e:
                        breaker.record_failure()
                        logger.warning("bilibili search GET raised: %s", e)
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=f"search GET failed: {e}",
                        )

                    if resp.status_code in (401, 403):
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="needs_login",
                            cards_emitted=emitted,
                            error_message=(
                                f"search {resp.status_code} (session invalid)"
                            ),
                        )
                    if resp.status_code in (429, 451, 503):
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="risk_control",
                            cards_emitted=emitted,
                            error_message=f"search {resp.status_code}",
                        )
                    if resp.status_code != 200:
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=f"search HTTP {resp.status_code}",
                        )

                    try:
                        body = resp.json()
                    except Exception as e:
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=f"search non-json: {e}",
                        )

                    code = body.get("code")
                    if code == -412:  # B 站 风控
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="risk_control",
                            cards_emitted=emitted,
                            error_message="bilibili code -412 (rate-limited)",
                        )
                    if code in (-101, -111):  # 未登录 / csrf 失败
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="needs_login",
                            cards_emitted=emitted,
                            error_message=f"bilibili code {code}",
                        )
                    if code != 0:
                        breaker.record_failure()
                        return SearchOutcome(
                            platform=self.platform, status="failed",
                            cards_emitted=emitted,
                            error_message=(
                                f"bilibili code {code}: {body.get('message', '')}"
                            ),
                        )

                    cards = self._extract_cards(body)
                    new_this_page = 0
                    for card in cards:
                        if emitted >= target_count or cancel_event.is_set():
                            break
                        if card.platform_video_id in seen_bvids:
                            continue
                        seen_bvids.add(card.platform_video_id)
                        emitted += 1
                        new_this_page += 1
                        card.rank_in_search = emitted
                        on_card(card)

                    on_progress(ProgressUpdate(
                        platform=self.platform, phase="scrolling",
                        got=emitted, target=target_count,
                    ))
                    logger.info(
                        "[bili-wbi] page=%d new=%d emitted=%d total_in_page=%d",
                        page_num, new_this_page, emitted, len(cards),
                    )

                    breaker.record_success()

                    if new_this_page == 0:
                        break
                    page_num += 1
                    if page_num > _PAGE_CAP:
                        break

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

    def _fetch_wbi_keys(self, client: Any) -> tuple[str, str]:
        """Fetch the rolling WBI keys from /x/web-interface/nav.

        Returns ``(img_key, sub_key)`` — basenames (no extension) of
        ``data.wbi_img.img_url`` and ``data.wbi_img.sub_url``. Mirrors
        MediaCrawler bilibili/client.py:137-161.
        """
        r = client.get(_NAV_URL)
        if r.status_code != 200:
            raise RuntimeError(f"nav HTTP {r.status_code}")
        body = r.json()
        wbi = (body.get("data") or {}).get("wbi_img") or {}
        img_url = wbi.get("img_url") or ""
        sub_url = wbi.get("sub_url") or ""
        if not img_url or not sub_url:
            raise RuntimeError(f"nav missing wbi_img: {body!r}")
        return _basename_no_ext(img_url), _basename_no_ext(sub_url)

    def _extract_cards(self, body: dict[str, Any]) -> list[VideoCard]:
        """Parse one /x/web-interface/wbi/search/type response into VideoCards."""
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
            play = item.get("play")
            like = item.get("like")
            cards.append(VideoCard(
                platform="bilibili",
                platform_video_id=bvid,
                url=f"https://www.bilibili.com/video/{bvid}",
                title=_strip_em(item.get("title", "")),
                author_name=item.get("author", "") or "",
                author_id=str(item.get("mid", "")) or "",
                cover_url=_normalize_url(item.get("pic", "")),
                duration_sec=parse_duration(item.get("duration", "")),
                play_count=(
                    play if isinstance(play, int)
                    else parse_int_count(str(play or ""))
                ),
                like_count=(
                    like if isinstance(like, int)
                    else parse_int_count(str(like or ""))
                ),
                published_at=_pubdate_to_iso(item.get("pubdate")),
                raw=item,
            ))
        return cards


def _basename_no_ext(url: str) -> str:
    """Extract ``<basename>`` from ``https://.../<basename>.<ext>``."""
    leaf = url.rsplit("/", 1)[-1]
    return leaf.rsplit(".", 1)[0]


def _strip_em(text: str) -> str:
    """B 站 search 结果会把命中关键词包成 ``<em class="keyword">...</em>``,strip 掉。"""
    if not text:
        return ""
    return re.sub(r"</?em[^>]*>", "", text)


def _normalize_url(u: str) -> str:
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    return u


def _pubdate_to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except Exception:
        return None
