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


@pytest.mark.asyncio
async def test_reap_stale_spares_actively_streamed_job():
    """A long job whose buffer outlives stale_after must NOT be reaped while
    an SSE client is attached — and its terminal event must still arrive."""
    bus = EventBus(stale_after_seconds=0.05)
    job = bus.create_job()

    drained: list[dict] = []

    async def consume():
        async for e in bus.stream(job):
            drained.append(e)
            if e["kind"] == "done":
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)  # exceed stale_after while stream attached + not done
    bus.publish(job, "stage", index=0)
    assert bus.reap_stale() == 0          # actively-streamed buffer survives
    assert bus.active_jobs() == 1
    bus.finish(job, document="/x.md")     # terminal event still reaches the stream
    await asyncio.wait_for(task, timeout=2.0)
    assert drained[-1]["kind"] == "done"


def test_reap_stale_spares_recently_active_buffer():
    """An orphan (no stream) that is STILL producing events keeps its buffer:
    last_activity bump means created_at age alone no longer triggers reaping."""
    bus = EventBus(stale_after_seconds=0.05)
    job = bus.create_job()
    time.sleep(0.1)                       # created_at is now older than stale_after...
    bus.publish(job, "stage", index=0)    # ...but a fresh publish bumps last_activity
    assert bus.reap_stale() == 0          # recent activity spares it
    assert bus.active_jobs() == 1


@pytest.mark.asyncio
async def test_second_concurrent_stream_rejected_without_disturbing_first():
    """两个客户端订阅同一 job_id：第二条 attach 必须被干净拒绝，且
    不能 reap 掉第一条仍在 drain 的 buffer（否则第一条会卡在孤儿 queue）。
    第一条必须照常收到全部事件 + 终态。"""
    bus = EventBus()
    job = bus.create_job()
    first_events: list[dict] = []

    async def first():
        async for e in bus.stream(job, ping_seconds=0.05):
            first_events.append(e)
            if e["kind"] == "done":
                return

    task = asyncio.create_task(first())
    await asyncio.sleep(0.02)          # 让第一条进入 stream() 并置 streaming=True
    bus.publish(job, "stage", index=0)
    await asyncio.sleep(0.02)          # 让第一条 drain 掉这条事件

    # 第二条并发 attach → 被拒绝，且不得删 buffer
    second_events = [e async for e in bus.stream(job)]
    assert second_events == [{"kind": "error", "error": f"already streaming: {job}"}]
    assert bus.active_jobs() == 1      # buffer 在被拒绝的 attach 后仍存活

    # 第一条仍正常：终态送达，且事件没被瓜分（index=0 在第一条手里）
    bus.finish(job, document="/x.md")
    await asyncio.wait_for(task, timeout=2.0)
    assert first_events[-1]["kind"] == "done"
    assert any(e.get("index") == 0 for e in first_events)


@pytest.mark.asyncio
async def test_stream_after_first_closes_succeeds():
    """第一条流结束（buffer 随 finally 回收）后，对该 job 的新 stream 得到
    干净的 unknown job_id（而不是 already streaming）——确认 streaming 标志
    不会泄漏。"""
    bus = EventBus()
    job = bus.create_job()
    bus.finish(job)
    drained = [e async for e in bus.stream(job)]   # 第一条：drain done 后 finally reap
    assert drained[-1]["kind"] == "done"
    # buffer 已回收，新 attach 走 unknown 分支（不是 already streaming）
    again = [e async for e in bus.stream(job)]
    assert again == [{"kind": "error", "error": f"unknown job_id: {job}"}]
