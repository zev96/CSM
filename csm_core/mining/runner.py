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

logger = logging.getLogger(__name__)


PUBLISH_EVERY_N_CARDS = 5
PUBLISH_EVERY_N_SECONDS = 10.0


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
                outcome: SearchOutcome = adapter.search(
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

        try:
            summary = mining_storage.finalize_job(job_id)
            self.publish("job.finished", {"job_id": job_id, "summary": summary})
        finally:
            # Always reap the cancel Event, even if finalize_job/publish raised.
            # Previously a SQL error in finalize_job would skip this and leak
            # one threading.Event per failed job for the sidecar lifetime.
            with self._lock:
                self._cancel_events.pop(job_id, None)
