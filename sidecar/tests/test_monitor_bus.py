"""MonitorBus broadcast tests."""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime

import pytest

from csm_sidecar.monitor_bus import MonitorBus, event_to_dict
from csm_sidecar.services.monitor_loop import MonitorEvent
from csm_core.monitor.base import MonitorResult


def _make_event(kind: str = "tick", task_id: int = 0) -> MonitorEvent:
    return MonitorEvent(
        kind=kind,  # type: ignore[arg-type]
        task_id=task_id,
        at=datetime.now(),
        dispatched=2 if kind == "tick" else None,
    )


def test_event_to_dict_serializes_datetime_and_result():
    res = MonitorResult(
        task_id=7, checked_at=datetime.now(), status="ok", rank=3, metric={"k": "v"},
    )
    e = MonitorEvent(kind="finished", task_id=7, at=datetime.now(), result=res)
    d = event_to_dict(e)
    assert d["kind"] == "finished"
    assert d["task_id"] == 7
    assert isinstance(d["at"], str)  # ISO datetime
    assert d["result"]["rank"] == 3
    assert d["result"]["metric"] == {"k": "v"}


@pytest.mark.asyncio
async def test_subscribe_receives_events_published_after_subscribe():
    bus = MonitorBus()
    received: list[dict] = []

    async def consume():
        async for ev in bus.subscribe(ping_seconds=5.0):  # wide gap → no ping noise
            if ev["kind"] == "ping":
                continue
            received.append(ev)
            if len(received) >= 2:
                return

    task = asyncio.create_task(consume())
    # Wait until subscribe() has actually registered the queue. Polling
    # subscriber_count is more robust than a fixed sleep.
    deadline = time.monotonic() + 1.0
    while bus.subscriber_count() == 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    bus.publish(_make_event(kind="tick"))
    bus.publish(_make_event(kind="started", task_id=1))
    await asyncio.wait_for(task, timeout=2.0)

    kinds = [e["kind"] for e in received]
    assert kinds == ["tick", "started"]


@pytest.mark.asyncio
async def test_multiple_subscribers_each_receive_events():
    bus = MonitorBus()
    a: list[dict] = []
    b: list[dict] = []

    async def consume(out):
        async for ev in bus.subscribe(ping_seconds=0.05):
            if ev["kind"] != "ping":
                out.append(ev)
            if len(out) >= 1:
                return

    ta = asyncio.create_task(consume(a))
    tb = asyncio.create_task(consume(b))
    await asyncio.sleep(0.05)
    bus.publish(_make_event(kind="tick"))
    await asyncio.wait_for(ta, timeout=2.0)
    await asyncio.wait_for(tb, timeout=2.0)

    assert len(a) == 1 and len(b) == 1


@pytest.mark.asyncio
async def test_ping_emitted_when_quiet():
    bus = MonitorBus()
    seen: list[str] = []

    async def consume():
        async for ev in bus.subscribe(ping_seconds=0.02):
            seen.append(ev["kind"])
            if len(seen) >= 2:
                return

    await asyncio.wait_for(consume(), timeout=1.0)
    assert "ping" in seen


def test_publish_to_no_subscribers_is_safe():
    bus = MonitorBus()
    # Should not raise even though no one is subscribed.
    bus.publish(_make_event())


@pytest.mark.asyncio
async def test_subscriber_count_tracks_lifetime():
    bus = MonitorBus()
    assert bus.subscriber_count() == 0

    started = threading.Event()

    async def consume():
        async for ev in bus.subscribe(ping_seconds=0.02):
            started.set()
            if ev["kind"] != "ping":
                return

    task = asyncio.create_task(consume())
    # Wait until subscribe has registered the queue.
    deadline = time.monotonic() + 1.0
    while bus.subscriber_count() == 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert bus.subscriber_count() == 1

    bus.publish(_make_event())
    await asyncio.wait_for(task, timeout=2.0)
    # Async-generator ``finally:`` runs at close time, not at task return.
    # Yield a couple of ticks for the GC + close to settle, then check.
    for _ in range(50):
        if bus.subscriber_count() == 0:
            break
        await asyncio.sleep(0.01)
    assert bus.subscriber_count() == 0


def test_monitor_event_kind_includes_captcha_states():
    """captcha 三个状态在 EventKind Literal 里。"""
    from typing import get_args
    from csm_sidecar.services.monitor_loop import EventKind

    args = set(get_args(EventKind))
    assert "captcha_required" in args
    assert "captcha_resolved" in args
    assert "captcha_timeout" in args


def test_event_to_dict_waiting_chrome_close_carries_remaining_s():
    from datetime import datetime
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_sidecar.monitor_bus import event_to_dict

    evt = MonitorEvent(
        kind="waiting_chrome_close",
        task_id=42,
        at=datetime(2026, 1, 1, 12, 0, 0),
        remaining_s=87,
    )
    out = event_to_dict(evt)
    assert out["kind"] == "waiting_chrome_close"
    assert out["task_id"] == 42
    assert out["remaining_s"] == 87


def test_event_to_dict_chrome_closed_minimal():
    from datetime import datetime
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_sidecar.monitor_bus import event_to_dict

    evt = MonitorEvent(
        kind="chrome_closed", task_id=42, at=datetime(2026, 1, 1, 12, 0, 0),
    )
    out = event_to_dict(evt)
    assert out["kind"] == "chrome_closed"
    assert out["task_id"] == 42
    # 不带 remaining_s / keyword 等额外字段


def test_event_to_dict_needs_captcha_carries_keyword_and_idx():
    from datetime import datetime
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_sidecar.monitor_bus import event_to_dict

    evt = MonitorEvent(
        kind="needs_captcha",
        task_id=42,
        at=datetime(2026, 1, 1, 12, 0, 0),
        keyword="iphone 15",
        kw_idx=5,
    )
    out = event_to_dict(evt)
    assert out["kind"] == "needs_captcha"
    assert out["keyword"] == "iphone 15"
    assert out["kw_idx"] == 5
