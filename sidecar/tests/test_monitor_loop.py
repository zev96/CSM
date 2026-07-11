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


def test_non_ok_return_emits_failed_not_finished(db_path: Path, sink, captured_events):
    """Adapter *returns* (not raises) a non-ok result (e.g. baidu breaker open
    returns status='risk_control'/'failed') → publish 'failed', NOT 'finished'.

    Regression: such results went through the normal-completion path and were
    published as 'finished', which fires the «监测任务完成» bell while the result
    has no metric.keywords so the pill shows «未跑» + a bogus "keyword #0"
    breakpoint — hiding the real failure. Now they surface as 'failed'.
    """
    task = _make_due_task()
    adapter = FakeAdapter(status="risk_control", rank=-1)
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
    assert "finished" not in kinds  # 关键回归点：不再假报「完成」
    assert kinds == ["started", "failed"]
    assert captured_events[-1].error is not None


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
    # 用固定本地时钟 12:00 + 同日 14:00 的日程 → 明确「未到点」，不受运行时的
    # 真实墙钟影响（原来用 now+2h 会在 22:00 后跨过午夜 → 无日期的 HH:MM 被当
    # 成今天的过去时刻 → 误判为 due，测试随时间闪烁）。
    from datetime import date

    fixed_local = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)
    task = MonitorTask(
        type="zhihu_question",
        name="future",
        target_url="https://www.zhihu.com/question/future",
        config={"target_brand": "x", "top_n": 5},
        schedule_cron="14:00",
        enabled=True,
    )
    task.id = storage.create_task(task)

    adapter = FakeAdapter()
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=1,
        schedule_clock=lambda: fixed_local,
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


# ── 3b. De-duplication: never dispatch a task that's already running ────────
class _GatedAdapter:
    """Blocks inside ``fetch`` until released, so the task stays *active*
    while we probe whether the scheduler re-dispatches it. Records every
    call so a duplicate dispatch is observable as ``call_count == 2``."""

    def __init__(self) -> None:
        self.platform = "zhihu_question"
        self.call_count = 0
        self._lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()

    def fetch(self, task: MonitorTask, **_kwargs: Any) -> MonitorResult:
        with self._lock:
            self.call_count += 1
        self.entered.set()
        self.release.wait(timeout=10)
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.now(),
            status="ok",
            rank=1,
            metric={"keywords": []},
        )


def test_tick_does_not_redispatch_running_task(db_path: Path, sink, captured_events):
    """A long-running task must NOT be re-dispatched by subsequent ticks
    before it finishes — ``last_check_at`` is only bumped on completion, so
    ``select_due`` keeps returning it, and the dispatcher must skip it."""
    task = _make_due_task()
    adapter = _GatedAdapter()
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=3600,
        clock=datetime.now,  # local clock so select_due sees the local HH:MM schedule
    )
    loop.start()
    try:
        loop.run_task_now(task.id)  # type: ignore[arg-type]
        assert adapter.entered.wait(timeout=5), "worker never entered fetch"
        # Task is still running. Fire ticks: select_due returns it again
        # (completion hasn't bumped last_check_at). Must be skipped.
        loop._tick()
        loop._tick()
        time.sleep(0.3)  # give any wrongly-submitted worker time to call fetch
        assert adapter.call_count == 1, "task was re-dispatched while still running"
    finally:
        adapter.release.set()
        loop.stop()


def test_run_task_now_rejects_already_running_task(db_path: Path, sink, captured_events):
    """Manual «启动监测» / run-now during an active run must not spin a
    second concurrent worker on the same task."""
    task = _make_due_task()
    adapter = _GatedAdapter()
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=3600,
        clock=datetime.now,
    )
    loop.start()
    try:
        loop.run_task_now(task.id)  # type: ignore[arg-type]
        assert adapter.entered.wait(timeout=5), "worker never entered fetch"
        # Second manual dispatch while the first is still running.
        fut = loop.run_task_now(task.id)  # type: ignore[arg-type]
        assert fut.result(timeout=5) is None, "duplicate dispatch should resolve to None"
        time.sleep(0.3)
        assert adapter.call_count == 1, "duplicate manual dispatch ran a second time"
        assert loop.is_task_active(task.id) is True  # type: ignore[arg-type]
    finally:
        adapter.release.set()
        loop.stop()


# ── 3c. Scheduling uses local wall-clock; stamps stay UTC ───────────────────
def test_scheduling_uses_local_wall_clock_not_utc(db_path: Path, sink, captured_events):
    """select_due must compare a task's local HH:MM schedule against LOCAL
    wall-clock. The bug: a single UTC clock drove both scheduling and
    stamping, so a 09:00-local daily task fired 8h late (17:00 CST). Here a
    task due at 11:00 local looks NOT due under the 02:00 UTC stamp clock,
    but MUST dispatch under the 12:00 local schedule clock."""
    from datetime import date

    d = date.today()
    local_now = datetime.combine(d, datetime.min.time()).replace(hour=12)  # 12:00 local
    utc_now = datetime.combine(d, datetime.min.time()).replace(hour=2)      # 02:00 UTC stamp
    task = MonitorTask(
        type="zhihu_question",
        name="sched",
        target_url="https://www.zhihu.com/question/sched",
        config={"target_brand": "x", "top_n": 5},
        schedule_cron="11:00",
        enabled=True,
    )
    task.id = storage.create_task(task)
    adapter = FakeAdapter()
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": adapter},
        tick_seconds=3600,
        clock=lambda: utc_now,
        schedule_clock=lambda: local_now,
    )
    loop.start()
    try:
        loop._tick()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any(e.kind == "finished" for e in captured_events):
                break
            time.sleep(0.05)
        assert adapter.call_count == 1, "task due at 11:00 local not dispatched at 12:00 local"
    finally:
        loop.stop()


# ── 3d. Single-keyword merge writes back result.rank ────────────────────────
def test_merge_partial_writes_back_result_rank(db_path: Path):
    """单关键词「启动监测」merge 后，result.rank 必须与重算的
    best_default_first_rank 一致。否则 should_alert 读到「那一个词的 rank」
    （未命中=-1）会误触发任务级告警 + 24h 冷却压掉真告警，DB rank 列还跟
    metric 永久 drift。"""
    from csm_sidecar.services.monitor_loop import _merge_partial_baidu_metric

    task = MonitorTask(
        type="baidu_keyword", name="t",
        target_url="baidu://t",
        config={"search_keywords": ["kwA", "kwB"]},
        schedule_cron="manual", enabled=True,
    )
    task.id = storage.create_task(task)
    # 先前快照：kwB 排到 #1
    prior = MonitorResult(
        task_id=task.id, checked_at=datetime.now(), status="ok", rank=1,
        metric={
            "keywords": [
                {"keyword": "kwA", "default_first_rank": -1, "default_matched_count": 0,
                 "default_results": [], "news_results": []},
                {"keyword": "kwB", "default_first_rank": 1, "default_matched_count": 1,
                 "default_results": [], "news_results": []},
            ],
            "best_default_first_rank": 1,
        },
    )
    storage.save_result(prior)
    # 单关键词重跑 kwA，这次没命中（rank=-1）
    partial = MonitorResult(
        task_id=task.id, checked_at=datetime.now(), status="ok", rank=-1,
        metric={
            "keywords": [
                {"keyword": "kwA", "default_first_rank": -1, "default_matched_count": 0,
                 "default_results": [], "news_results": []},
            ],
            "best_default_first_rank": -1,
        },
    )
    _merge_partial_baidu_metric(partial, "kwA", task.id)
    assert partial.metric["best_default_first_rank"] == 1
    assert partial.rank == 1, "result.rank 必须回写为跨全部关键词的 best"


# ── 3e. Alert config hot-reload ─────────────────────────────────────────────
def test_set_alert_config_updates_thresholds(db_path: Path, sink):
    """PATCH /api/config 改 alert_top_n / alert_cooldown_hours 要即时生效，
    不该等重启 sidecar（reconfigure 之前只推 adapter 设置，漏了 loop 的告警阈值）。"""
    loop = MonitorLoop(
        event_sink=sink,
        adapters={"zhihu_question": FakeAdapter()},
        alert_top_n=5,
        cooldown_hours=24,
        tick_seconds=3600,
    )
    loop.set_alert_config(alert_top_n=7, cooldown_hours=12)
    assert loop._alert_top_n == 7  # noqa: SLF001
    assert loop._cooldown_hours == 12  # noqa: SLF001


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
