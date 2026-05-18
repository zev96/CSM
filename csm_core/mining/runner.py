"""Orchestrates one MiningJob: pick adapters, run each platform serially,
stream cards to storage, publish progress events.

Threading: one job runs on one worker thread (sidecar's
``mining_service`` ThreadPoolExecutor with max_workers=1). Inside the
job we DO NOT spawn additional threads — adapters block on
patchright sync API which is already greenlet-bound to this thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from csm_core.mining import storage as mining_storage
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import SearchAdapter
from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter
from csm_core.monitor.drivers.risk_detector import RiskControlException

logger = logging.getLogger(__name__)


PUBLISH_EVERY_N_CARDS = 5
PUBLISH_EVERY_N_SECONDS = 10.0

# Domains that indicate a login-wall redirect (non-Baidu — Baidu is handled
# by the baidu adapter's own risk_detector).  Matched as substrings in
# the page URL after a 0-result search.
_LOGIN_WALL_DOMAINS = (
    "passport.douyin.com",
    "passport.kuaishou.com",
    "passport.bilibili.com",
    "id.kuaishou.com",
    "login.douyin.com",
    "login.bilibili.com",
)


def _call_adapter_with_status(
    adapter: SearchAdapter,
    *,
    keyword: str,
    target_count: int,
    on_card: "Callable",
    on_progress: "Callable",
    cancel_event: "threading.Event",
    get_current_url: "Callable[[], str] | None" = None,
) -> SearchOutcome:
    """Call adapter.search() and map risk / login exceptions to SearchOutcome.status.

    ``get_current_url``: optional zero-arg callable that returns the browser's
    current URL after the search call.  Passed by the runner for platforms where
    the page is managed externally (e.g. Task-6 pool); left None for adapters
    that manage their own page internally (all current adapters do this, so
    login-wall detection via URL is only opportunistic here — the adapters
    themselves already return needs_login / risk_control in those cases).
    """
    try:
        outcome = adapter.search(
            keyword=keyword,
            target_count=target_count,
            on_card=on_card,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
    except RiskControlException as e:
        return SearchOutcome(
            platform=adapter.platform,
            status="risk_control",
            cards_emitted=0,
            error_message=str(e),
            status_detail=f"{e.signal.layer}: {e.signal.detail}",
        )

    # Opportunistic login-wall detection: if the adapter returned 0 cards and
    # the page ended up on a login wall URL, upgrade to login_required.
    if outcome.cards_emitted == 0 and outcome.status not in ("cancelled", "failed"):
        current_url = ""
        if get_current_url is not None:
            try:
                current_url = get_current_url() or ""
            except Exception:
                pass
        if current_url and any(d in current_url for d in _LOGIN_WALL_DOMAINS):
            outcome.status = "needs_login"
            outcome.status_detail = f"page redirected to login wall: {current_url}"

    return outcome


EventPublisher = Callable[[str, dict], None]
"""Callable injected by mining_service to publish to the event bus.
Signature: ``publish(kind, payload)`` — kind ∈ {"job.started", "job.progress",
"job.platform_done", "job.finished", "login.required"}."""


def get_adapter(platform: Platform) -> SearchAdapter:
    if platform == "bilibili":
        return BilibiliSearchAdapter()
    if platform == "kuaishou":
        return KuaishouSearchAdapter()
    if platform == "douyin":
        return DouyinSearchAdapter()
    raise ValueError(f"unknown platform: {platform}")


class MiningRunner:
    def __init__(self, *, publish: EventPublisher) -> None:
        self.publish = publish
        self._cancel_events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    def register_cancel_event(self, job_id: int) -> threading.Event:
        with self._lock:
            if job_id not in self._cancel_events:
                self._cancel_events[job_id] = threading.Event()
            return self._cancel_events[job_id]

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
            return True
        return False

    def run(self, job_id: int) -> None:
        job = mining_storage.get_job(job_id)
        if job is None:
            logger.warning("MiningRunner.run: unknown job %d", job_id)
            return
        cancel_event = self.register_cancel_event(job_id)
        mining_storage.mark_started(job_id)
        self.publish("job.started", {"job_id": job_id, "keyword": job["keyword"]})

        # Per-card publisher state, reset between platforms.
        last_pub_time = [0.0]
        last_pub_count = [0]

        for platform in job["platforms"]:
            if cancel_event.is_set():
                mining_storage.update_platform_progress(
                    job_id, platform, got=0, target=job["target_per_platform"], phase="cancelled",
                )
                continue

            adapter = get_adapter(platform)

            def _on_card(card: VideoCard, platform=platform) -> None:
                try:
                    mining_storage.upsert_video_and_link(card, job_id)
                except Exception as e:
                    logger.exception("upsert_video_and_link failed: %s", e)

            def _on_progress(pu: ProgressUpdate, platform=platform) -> None:
                mining_storage.update_platform_progress(
                    job_id, platform,
                    got=pu.got, target=pu.target, phase=pu.phase, note=pu.note,
                )
                now = time.monotonic()
                if (
                    pu.phase != "scrolling"
                    or pu.got - last_pub_count[0] >= PUBLISH_EVERY_N_CARDS
                    or now - last_pub_time[0] >= PUBLISH_EVERY_N_SECONDS
                ):
                    last_pub_count[0] = pu.got
                    last_pub_time[0] = now
                    self.publish("job.progress", {
                        "job_id": job_id, "platform": platform, "phase": pu.phase,
                        "got": pu.got, "target": pu.target, "note": pu.note,
                    })
                if pu.phase == "needs_login":
                    self.publish("login.required", {"job_id": job_id, "platform": platform})

            try:
                outcome: SearchOutcome = _call_adapter_with_status(
                    adapter,
                    keyword=job["keyword"],
                    target_count=job["target_per_platform"],
                    on_card=_on_card,
                    on_progress=_on_progress,
                    cancel_event=cancel_event,
                )
            except Exception as e:
                logger.exception("adapter %s threw — recording as failed", platform)
                mining_storage.update_platform_progress(
                    job_id, platform,
                    got=0, target=job["target_per_platform"],
                    phase="failed", note=str(e)[:200],
                )
                self.publish("job.platform_done", {
                    "job_id": job_id, "platform": platform,
                    "status": "failed", "count": 0, "error": str(e)[:200],
                })
                continue

            # Final platform progress with outcome status.
            mining_storage.update_platform_progress(
                job_id, platform,
                got=outcome.cards_emitted,
                target=job["target_per_platform"],
                phase=outcome.status if outcome.status != "done" else "done",
            )
            self.publish("job.platform_done", {
                "job_id": job_id, "platform": platform,
                "status": outcome.status, "count": outcome.cards_emitted,
                "error": outcome.error_message,
            })

        summary = mining_storage.finalize_job(job_id)
        self.publish("job.finished", {"job_id": job_id, "summary": summary})

        with self._lock:
            self._cancel_events.pop(job_id, None)
