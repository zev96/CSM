"""Broadcast pub/sub for global monitor events.

Differs from :mod:`event_bus` in that there's no per-job ``job_id`` —
every subscriber sees every event. Models the legacy GUI's
``monitor_controller.alert_triggered`` signal which the entire UI shell
listened to.

Threading
---------
The MonitorLoop publishes from worker threads (APScheduler-driven).
Subscribers are async generators in FastAPI handler context. We bridge
via per-subscriber ``threading.Queue`` plus ``asyncio.to_thread(q.get)``
— same pattern as :mod:`event_bus`, but fan-out instead of fan-in.

Backpressure
------------
Each subscriber owns a bounded queue. If a slow client lags, we drop new
events for that subscriber rather than blocking the publisher. Live UIs
care about freshness more than completeness; the snapshot endpoint
(``GET /api/monitor/results``) is the source of truth for missed events.
"""
from __future__ import annotations

import asyncio
import logging
import queue as _queue
import threading
from datetime import datetime
from typing import Any, AsyncIterator

from csm_sidecar.services.monitor_loop import MonitorEvent

logger = logging.getLogger(__name__)


class MonitorBus:
    def __init__(self, *, queue_size: int = 100) -> None:
        self._subscribers: list[_queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._queue_size = queue_size

    def publish(self, event: MonitorEvent) -> None:
        """Called from MonitorLoop worker threads. Non-blocking."""
        payload = event_to_dict(event)
        with self._lock:
            queues = list(self._subscribers)
        for q in queues:
            try:
                q.put_nowait(payload)
            except _queue.Full:
                # Slow consumer — drop. UI can re-fetch state from snapshot endpoint.
                logger.debug("monitor_bus subscriber queue full, dropping event")

    async def subscribe(
        self, *, ping_seconds: float = 15.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every event from now until the caller disconnects.

        Inserts a ``{"kind": "ping"}`` heartbeat every ``ping_seconds``
        of silence so EventSource clients don't time out.
        """
        q: _queue.Queue[dict[str, Any]] = _queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.append(q)
        try:
            while True:
                try:
                    event = await asyncio.to_thread(q.get, True, ping_seconds)
                except _queue.Empty:
                    yield {"kind": "ping"}
                    continue
                yield event
        finally:
            with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def event_to_dict(event: MonitorEvent) -> dict[str, Any]:
    """Serialize a MonitorEvent for JSON transport."""
    out: dict[str, Any] = {
        "kind": event.kind,
        "task_id": event.task_id,
        "at": event.at.isoformat() if isinstance(event.at, datetime) else event.at,
    }
    if event.error is not None:
        out["error"] = event.error
    if event.dispatched is not None:
        out["dispatched"] = event.dispatched
    # `progress` events carry N/M counters; the frontend (BaiduRankingPage)
    # uses these to render a per-task progress bar (3 / 10 etc.).
    if event.progress_current is not None:
        out["progress_current"] = event.progress_current
    if event.progress_total is not None:
        out["progress_total"] = event.progress_total
    # `risk_control` events carry breakpoint position for frontend banner.
    if event.last_resumed_keyword is not None:
        out["last_resumed_keyword"] = event.last_resumed_keyword
    if event.total_keywords is not None:
        out["total_keywords"] = event.total_keywords
    if event.result is not None:
        # MonitorResult is a Pydantic v2 model; mode='json' converts datetimes.
        out["result"] = event.result.model_dump(mode="json")
    if event.remaining_s is not None:
        out["remaining_s"] = event.remaining_s
    if event.keyword is not None:
        out["keyword"] = event.keyword
    if event.kw_idx is not None:
        out["kw_idx"] = event.kw_idx
    return out


# Process-global instance.
monitor_bus = MonitorBus()
