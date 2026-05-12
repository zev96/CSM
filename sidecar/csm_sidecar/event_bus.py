"""In-process pub/sub for SSE streaming.

The legacy GUI used QSignal to push pipeline progress; sidecar uses this
bus instead. Each long-running job (article generate, batch run, dedup
build) creates a queue keyed by ``job_id``; the worker thread publishes
events into the queue, and the SSE endpoint drains it asynchronously.

Threading model
---------------
The bus is **thread-safe by construction**: queue operations are atomic,
and the SSE generator reads via ``asyncio.to_thread(queue.get, ...)`` so
the FastAPI event loop never blocks on a slow worker. No asyncio.Queue —
the worker is pure sync (csm_core.pipeline.* is blocking) and we want it
to push without caring whether the SSE client is connected yet.

Lifetime
--------
A queue is allocated by ``create_job``, drained by ``stream``, and
disposed when the stream sees the ``done`` sentinel. If a client never
connects, the queue is reaped by ``reap_stale`` (called periodically by
the lifespan handler in stage A3.x).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class _JobBuffer:
    queue: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)
    created_at: float = field(default_factory=time.monotonic)
    done: bool = False


class EventBus:
    """Single-process event router. Construct one, share it everywhere."""

    # Sentinel event kinds that close the stream loop.
    SENTINEL_KINDS = ("done", "error")

    def __init__(self, *, stale_after_seconds: float = 600.0) -> None:
        self._buffers: dict[str, _JobBuffer] = {}
        self._lock = threading.Lock()
        self._stale_after = stale_after_seconds

    # ── public API ──────────────────────────────────────────────────────
    def new_job_id(self) -> str:
        return uuid.uuid4().hex

    def create_job(self, job_id: str | None = None) -> str:
        """Allocate a queue. Returns the job_id (newly minted if None)."""
        job_id = job_id or self.new_job_id()
        with self._lock:
            self._buffers[job_id] = _JobBuffer()
        return job_id

    def publish(self, job_id: str, kind: str, **data: Any) -> None:
        """Non-blocking. Silently no-ops if the job_id was already reaped."""
        with self._lock:
            buf = self._buffers.get(job_id)
        if buf is None:
            logger.debug("publish to unknown job_id=%s kind=%s — dropped", job_id, kind)
            return
        if buf.done and kind not in self.SENTINEL_KINDS:
            # Late publish after done — drop. Keeps streams from re-opening
            # on cleanup races.
            return
        event: dict[str, Any] = {"kind": kind, **data}
        buf.queue.put(event)

    def finish(self, job_id: str, **data: Any) -> None:
        """Publish a ``done`` sentinel + mark the buffer for reaping."""
        with self._lock:
            buf = self._buffers.get(job_id)
            if buf is None:
                return
            buf.done = True
        buf.queue.put({"kind": "done", **data})

    def fail(self, job_id: str, error: str, **data: Any) -> None:
        with self._lock:
            buf = self._buffers.get(job_id)
            if buf is None:
                return
            buf.done = True
        buf.queue.put({"kind": "error", "error": error, **data})

    async def stream(self, job_id: str, *, ping_seconds: float = 15.0) -> AsyncIterator[dict[str, Any]]:
        """Async generator for SSE.

        Yields each event dict as it arrives. When a ``done`` or ``error``
        event appears, yields it and then returns. If the queue is silent
        for ``ping_seconds`` we yield a ``{"kind": "ping"}`` so the
        browser-side EventSource doesn't time out the connection.
        """
        with self._lock:
            buf = self._buffers.get(job_id)
        if buf is None:
            yield {"kind": "error", "error": f"unknown job_id: {job_id}"}
            return
        try:
            while True:
                try:
                    event = await asyncio.to_thread(buf.queue.get, True, ping_seconds)
                except queue.Empty:
                    yield {"kind": "ping"}
                    continue
                yield event
                if event["kind"] in self.SENTINEL_KINDS:
                    return
        finally:
            self._reap(job_id)

    def reap_stale(self) -> int:
        """Drop buffers that finished long ago without ever being streamed.

        Returns the number reaped. Call periodically (e.g. once a minute).
        """
        now = time.monotonic()
        reaped = 0
        with self._lock:
            stale = [
                jid for jid, b in self._buffers.items()
                if (now - b.created_at) > self._stale_after
            ]
            for jid in stale:
                del self._buffers[jid]
                reaped += 1
        if reaped:
            logger.debug("EventBus reaped %d stale jobs", reaped)
        return reaped

    def active_jobs(self) -> int:
        with self._lock:
            return len(self._buffers)

    # ── private ─────────────────────────────────────────────────────────
    def _reap(self, job_id: str) -> None:
        with self._lock:
            self._buffers.pop(job_id, None)


# Process-global instance. Routes import this; tests can monkeypatch.
bus = EventBus()
