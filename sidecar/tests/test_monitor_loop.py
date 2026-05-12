"""Tests for the APScheduler-driven monitor dispatcher.

The unit under test is :class:`csm_sidecar.services.monitor_loop.MonitorLoop`.
csm_core itself is left alone — these tests verify the sidecar wiring
correctly composes ``select_due``, ``slot``, ``should_alert``, and the
storage layer.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_sidecar.services.monitor_loop import MonitorEvent, MonitorLoop


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh per-test sqlite DB. The storage module is process-singleton, so
    we reset its module-level state between tests."""
    db_file = tmp_path / "monitor.db"
    # Reset storage globals — init_db rejects re-init at a different path.
    monkeypatch.setattr(storage, "_db_path", None, raising=True)
    monkeypatch.setattr(storage, "_initialized", False, raising=True)
    # Threading-local connections from any leaked prior thread are also
    # invalid against the new DB; clearing them via a fresh threading.local
    # is the cleanest reset.
    monkeypatch.setattr(storage, "_local", threading.local(), raising=True)
    storage.init_db(db_file)
    return db_file


class FakeAdapter:
    """In-process stand-in for a platform adapter. Records every call."""

    def __init__(self, *, rank: int = 1, status: str = "ok",
                 raise_exc: BaseException | None = None) -> None:
        self.platform = "zhihu_question"
        self.rank = rank
        self.status = status
        self.raise_exc = raise_exc
        self.call_count = 0
        self.lock = threading.Lock()

    def fetch(self, task: MonitorTask) -> MonitorResult:
        with self.lock:
            self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.now(),
            status=self.status,  # type: ignore[arg-type]
            rank=self.rank,
            metric={"called": self.call_count},
        )


@pytest.fixture
def captured_events() -> list[MonitorEvent]:
    return []


@pytest.fixture
def sink(captured_events: list[MonitorEvent]):
    return captured_events.append


def _make_due_task(name: str = "t1") -> MonitorTask:
    """A task whose schedule is 'now-1min' so select_due returns it today."""
    past = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")
    task = MonitorTask(
        type="zhihu_question",
        name=name,
        target_url=f"https://www.zhihu.com/question/{name}",
        config={"target_brand": "x", "top_n": 5},
        schedule_cron=past,
        enabled=True,
    )
    task.id = storage.create_task(task)
    return task


# ── 1. Manual dispatch (no real periodic tick) ──────────────────────────────
def test_run_task_now_emits_started_finished(db_path: Path, sink, captured_events):
    task = _make_due_task()
    adapter = FakeAdapter(rank=3)
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=3600,  # effectively disabled for this test
    )
    loop.start()
    try:
        future = loop.run_task_now(task.id)  # type: ignore[arg-type]
        result = future.result(timeout=5)
        assert result is not None
        assert result.rank == 3
        assert adapter.call_count == 1
    finally:
        loop.stop()

    kinds = [e.kind for e in captured_events]
    assert kinds == ["started", "finished"]
    assert captured_events[1].result is not None
    assert captured_events[1].result.rank == 3


def test_adapter_exception_is_isolated(db_path: Path, sink, captured_events):
    task = _make_due_task()
    adapter = FakeAdapter(raise_exc=RuntimeError("boom"))
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=3600,
    )
    loop.start()
    try:
        loop.run_task_now(task.id).result(timeout=5)  # type: ignore[arg-type]
    finally:
        loop.stop()

    kinds = [e.kind for e in captured_events]
    assert kinds == ["started", "failed"]
    err = captured_events[-1].error
    assert err is not None and "RuntimeError" in err and "boom" in err

    # No result row was persisted — the failure short-circuits before save_result.
    assert storage.list_results(task.id) == []  # type: ignore[arg-type]


def test_run_task_now_unknown_id_emits_failed(db_path: Path, sink, captured_events):
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": FakeAdapter()},
        tick_seconds=3600,
    )
    loop.start()
    try:
        loop.run_task_now(9999).result(timeout=5)
    finally:
        loop.stop()

    assert [e.kind for e in captured_events] == ["failed"]
    assert captured_events[0].error == "task not found"


# ── 2. Alert cooldown ───────────────────────────────────────────────────────
def test_alert_fires_first_time_then_cools_down(db_path: Path, sink, captured_events):
    task = _make_due_task()
    # rank=10, alert_top_n=5 → out of top_n → alert candidate (status=ok required)
    adapter = FakeAdapter(rank=10, status="ok")
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        alert_top_n=5,
        cooldown_hours=24,
        tick_seconds=3600,
    )
    loop.start()
    try:
        loop.run_task_now(task.id).result(timeout=5)  # type: ignore[arg-type]
        loop.run_task_now(task.id).result(timeout=5)  # type: ignore[arg-type]
    finally:
        loop.stop()

    alert_count = sum(1 for e in captured_events if e.kind == "alert")
    finished_count = sum(1 for e in captured_events if e.kind == "finished")
    assert finished_count == 2
    # Cooldown bites the second run within the same 24h window.
    assert alert_count == 1


# ── 3. Periodic tick — uses fast tick_seconds + injected clock ──────────────
def test_periodic_tick_dispatches_due_tasks(db_path: Path, sink, captured_events):
    task = _make_due_task()
    adapter = FakeAdapter(rank=2)
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=1,  # fast for test
    )
    loop.start()
    try:
        # Wait for at least one tick + worker completion. Tick runs on
        # APScheduler thread; dispatch goes to ThreadPoolExecutor; we
        # poll for the finished event up to a generous bound.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any(e.kind == "finished" for e in captured_events):
                break
            time.sleep(0.05)
        assert adapter.call_count >= 1
    finally:
        loop.stop()

    kinds = [e.kind for e in captured_events]
    # At least one "tick" with dispatched>=1, then started, then finished.
    assert "tick" in kinds
    assert "started" in kinds
    assert "finished" in kinds


def test_tick_with_no_due_tasks_emits_zero_dispatch(db_path: Path, sink, captured_events):
    # Create a task that's NOT due: schedule far in the future.
    future = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")
    task = MonitorTask(
        type="zhihu_question",
        name="future",
        target_url="https://www.zhihu.com/question/future",
        config={"target_brand": "x", "top_n": 5},
        schedule_cron=future,
        enabled=True,
    )
    task.id = storage.create_task(task)

    adapter = FakeAdapter()
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=1,
    )
    loop.start()
    try:
        # Let one or two ticks fire.
        time.sleep(1.5)
    finally:
        loop.stop()

    assert adapter.call_count == 0
    tick_events = [e for e in captured_events if e.kind == "tick"]
    assert tick_events, "expected at least one tick event"
    assert all((t.dispatched or 0) == 0 for t in tick_events)


# ── 4. Restart safety ───────────────────────────────────────────────────────
def test_start_stop_start_is_safe(db_path: Path, sink):
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": FakeAdapter()},
        tick_seconds=1,
    )
    loop.start()
    assert loop.is_running()
    loop.stop()
    assert not loop.is_running()
    loop.start()
    assert loop.is_running()
    loop.stop()
    assert not loop.is_running()


def test_double_start_is_idempotent(db_path: Path, sink):
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": FakeAdapter()},
        tick_seconds=1,
    )
    loop.start()
    loop.start()  # second call must not raise / leak threads
    assert loop.is_running()
    loop.stop()


def test_double_stop_is_idempotent(db_path: Path, sink):
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": FakeAdapter()},
        tick_seconds=1,
    )
    loop.start()
    loop.stop()
    loop.stop()  # second call must not raise


# ── 5. Sink failure must not kill the loop ──────────────────────────────────
def test_sink_exception_does_not_break_loop(db_path: Path):
    task = _make_due_task()
    adapter = FakeAdapter(rank=2)

    raised: list[int] = []

    def bad_sink(_e: MonitorEvent) -> None:
        raised.append(1)
        raise RuntimeError("sink boom")

    loop = MonitorLoop(
        event_sink=bad_sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=3600,
    )
    loop.start()
    try:
        # Should complete cleanly even though every event raises.
        result = loop.run_task_now(task.id).result(timeout=5)  # type: ignore[arg-type]
        assert result is not None
    finally:
        loop.stop()

    # Started + finished both raised → sink invoked twice at least.
    assert len(raised) >= 2
    # And the result was still persisted (the sink failure is downstream of save_result).
    assert len(storage.list_results(task.id)) == 1  # type: ignore[arg-type]
