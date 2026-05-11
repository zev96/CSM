"""EventBus unit tests — pure async, no FastAPI in this file."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from csm_sidecar.event_bus import EventBus


@pytest.mark.asyncio
async def test_publish_then_stream_yields_events():
    bus = EventBus()
    job = bus.create_job()
    bus.publish(job, "stage", stage="A", index=0)
    bus.publish(job, "stage", stage="B", index=1)
    bus.finish(job, document="/tmp/x.md")

    events: list[dict] = []
    async for event in bus.stream(job):
        events.append(event)
    assert [e["kind"] for e in events] == ["stage", "stage", "done"]
    assert events[0]["stage"] == "A"
    assert events[2]["document"] == "/tmp/x.md"


@pytest.mark.asyncio
async def test_late_subscriber_still_drains_buffered_events():
    """Worker can publish before SSE client connects — events must survive."""
    bus = EventBus()
    job = bus.create_job()
    # Publish many BEFORE stream() is called.
    for i in range(5):
        bus.publish(job, "stage", index=i)
    bus.finish(job)

    events = []
    async for e in bus.stream(job):
        events.append(e)
    assert len([e for e in events if e["kind"] == "stage"]) == 5


@pytest.mark.asyncio
async def test_unknown_job_id_yields_error_then_returns():
    bus = EventBus()
    events = []
    async for e in bus.stream("does-not-exist"):
        events.append(e)
    assert events == [{"kind": "error", "error": "unknown job_id: does-not-exist"}]


@pytest.mark.asyncio
async def test_fail_propagates_error_kind():
    bus = EventBus()
    job = bus.create_job()
    bus.fail(job, error="boom")
    events = []
    async for e in bus.stream(job):
        events.append(e)
    assert events == [{"kind": "error", "error": "boom"}]


@pytest.mark.asyncio
async def test_ping_emitted_when_quiet():
    """When the worker is silent for ping_seconds, stream yields a ping
    event so the EventSource client doesn't time out."""
    bus = EventBus()
    job = bus.create_job()

    seen: list[str] = []

    async def consume():
        async for e in bus.stream(job, ping_seconds=0.05):
            seen.append(e["kind"])
            if len(seen) >= 2:
                bus.finish(job)
            if e["kind"] == "done":
                return

    await asyncio.wait_for(consume(), timeout=2.0)
    assert "ping" in seen
    assert seen[-1] == "done"


@pytest.mark.asyncio
async def test_publish_after_finish_is_dropped():
    bus = EventBus()
    job = bus.create_job()
    bus.finish(job)
    # This should be silently dropped.
    bus.publish(job, "stage", stage="late")
    events = []
    async for e in bus.stream(job):
        events.append(e)
    # Only the done sentinel.
    assert [e["kind"] for e in events] == ["done"]


def test_publish_to_unknown_job_does_not_raise():
    """Workers shouldn't have to check whether a job was reaped first."""
    bus = EventBus()
    bus.publish("never-created", "stage", stage="x")  # silent no-op


def test_active_jobs_count():
    bus = EventBus()
    assert bus.active_jobs() == 0
    bus.create_job()
    bus.create_job()
    assert bus.active_jobs() == 2


def test_reap_stale_drops_old_buffers():
    bus = EventBus(stale_after_seconds=0.05)
    bus.create_job("old1")
    bus.create_job("old2")
    time.sleep(0.1)
    assert bus.reap_stale() == 2
    assert bus.active_jobs() == 0


@pytest.mark.asyncio
async def test_concurrent_publish_from_threads_is_safe():
    """Many worker threads publishing into one job should all be delivered."""
    bus = EventBus()
    job = bus.create_job()
    n = 50

    def worker(i: int):
        bus.publish(job, "stage", index=i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bus.finish(job)

    events = []
    async for e in bus.stream(job):
        events.append(e)
    stage_indices = sorted(e["index"] for e in events if e["kind"] == "stage")
    assert stage_indices == list(range(n))
