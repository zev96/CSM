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
import random
import threading
import time
from typing import Any
from urllib.parse import quote

from csm_core.browser_infra import mining_browser
from csm_core.mining.config import PAGE_DELAY_RANGE_SEC, get_max_attempts
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms import _risk
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
        max_attempts: int | None = None,
    ) -> SearchOutcome:
        if max_attempts is None:
            max_attempts = get_max_attempts("douyin")
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
                # 抖音视频搜索实际走 /aweme/v1/web/search/item/?...&search_channel=aweme_video_web
                # 旧的 /aweme/v1/web/general/search/single 是综合搜索;我们 URL 带 ?type=video
                # 落在视频 tab,走 item 端点。两个都拦,谁先来用谁。
                # —— 如果后续抓不到 cards 怀疑 URL 又变了,临时加一行
                # ``if "/aweme/" in response.url: logger.info(response.url)``
                # 就能看到所有 aweme XHR 的真实 path,比再调一遍诊断流水线快。
                if (
                    "/aweme/v1/web/search/item/" not in response.url
                    and "/aweme/v1/web/general/search/single" not in response.url
                ):
                    return
                try:
                    body = response.json()
                except Exception:
                    return
                # 抖音偶发返回 JSON list/string（A/B 试验或风控降级页），
                # 直接 body.get() 会 raise AttributeError 渗回 Patchright
                # 的 response 事件循环 → "Listener raised" 日志噪音 + 抓取
                # 早早异常停止。先确认 dict 再读字段。
                if not isinstance(body, dict):
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

            # Give the React bundle a beat to hydrate + emit the first XHR
            # before we start scrolling. Network-idle is best-effort: many
            # pages keep periodic heartbeats running, in which case the wait
            # times out cleanly and we proceed to the scroll loop anyway.
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception as e:
                logger.info("douyin networkidle wait timed out: %s", e)

            for _ in range(max_attempts):
                if cancel_event.is_set() or emitted >= target_count:
                    break
                # 4-layer detection (URL / HTTP / DOM / page text) replaces
                # the old URL-only check, so SPA captcha modals overlaid on
                # /search/* (which don't change the URL) get caught too.
                # FEASIBILITY_ANALYSIS.md §1.1 Bug 2.
                if _risk.detect(page):
                    # v0.5.6: 不再立刻 bail —— 浏览器是 headed 状态，用户能
                    # 看到 captcha 并手解。Poll 等 _risk.detect 转 False（解
                    # 决/页面变化），超时才真的 bail。这样抖音首次冷启动
                    # 撞 captcha 不再是"直接失败"的死路。
                    if not _wait_for_captcha_cleared(
                        page, on_progress, cancel_event,
                        emitted=emitted, target_count=target_count,
                        platform=self.platform,
                    ):
                        risk_detected = True
                        break
                    # captcha 解掉，回 scrolling 状态继续抓
                    on_progress(ProgressUpdate(
                        platform=self.platform, phase="scrolling",
                        got=emitted, target=target_count,
                    ))
                    continue
                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(random.uniform(*PAGE_DELAY_RANGE_SEC))

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
            # Borrow MediaCrawler douyin/core.py:200-209 — Douyin returns
            # either a flat aweme_info OR a mix bundle whose first slot
            # carries the actual aweme. CSM previously only handled the flat
            # case, which silently dropped mixed-rank results (sometimes the
            # majority of a search page). FEASIBILITY_ANALYSIS.md §1.1 Bug 1b.
            info = item.get("aweme_info")
            if info is None:
                mix = item.get("aweme_mix_info") or {}
                items = mix.get("mix_items") or []
                info = items[0] if items else None
            if not isinstance(info, dict):
                continue
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


# v0.5.6 — captcha wait helper. Extracted so we can unit-test the polling
# loop without spinning up an actual Patchright browser.
_CAPTCHA_WAIT_TIMEOUT_S = 300.0   # 5 min — generous for image+slider captchas
_CAPTCHA_POLL_INTERVAL_S = 3.0    # check every 3s; balances responsiveness vs CPU


def _wait_for_captcha_cleared(
    page: Any,
    on_progress: Any,
    cancel_event: threading.Event,
    *,
    emitted: int,
    target_count: int,
    platform: Platform,
) -> bool:
    """Poll ``_risk.detect`` until the page is no longer flagged.

    Returns True if the user solved the captcha in time (or page navigated
    away from the risk page), False on timeout / cancellation.

    The headed Patchright browser stays visible the whole time, so the user
    can interact with the captcha widget directly. We emit
    ``captcha_waiting`` progress updates every poll so the UI can show a
    distinct "需验证" state instead of the misleading 抓取中 spinner.
    """
    signal = _risk.detect_signal(page)
    layer = getattr(signal, "layer", "?") if signal else "?"
    logger.info(
        "%s captcha detected (layer=%s); waiting up to %.0fs for user to solve",
        platform, layer, _CAPTCHA_WAIT_TIMEOUT_S,
    )
    on_progress(ProgressUpdate(
        platform=platform, phase="captcha_waiting",
        got=emitted, target=target_count,
        note="请在弹出的浏览器中手动完成验证，验证后将自动继续抓取",
    ))
    deadline = time.monotonic() + _CAPTCHA_WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            logger.info("%s captcha wait cancelled by user", platform)
            return False
        time.sleep(_CAPTCHA_POLL_INTERVAL_S)
        if not _risk.detect(page):
            logger.info("%s captcha cleared, resuming scroll", platform)
            return True
    logger.warning("%s captcha wait timed out after %.0fs", platform, _CAPTCHA_WAIT_TIMEOUT_S)
    return False


# NB: the URL-only ``_is_captcha_or_login`` helper that used to live here
# was replaced by the 4-layer ``_risk.detect`` call in the scroll loop —
# Douyin's slider/image captchas open as in-page modals without changing
# the URL, so URL-only detection missed them. See FEASIBILITY_ANALYSIS.md
# §1.1 Bug 2 + csm_core/monitor/drivers/risk_detector.py for the full
# detection stack we now reuse.
