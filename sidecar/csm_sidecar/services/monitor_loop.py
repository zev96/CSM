"""APScheduler-driven monitor dispatch loop.

This is the sidecar replacement for the legacy QTimer + QThread driver
that lived in ``csm_gui`` (``MonitorWorker`` + monitor_controller's
periodic tick). The Qt-free decision logic is reused as-is from
``csm_core.monitor.scheduler`` / ``.notify`` / ``.storage``; what this
module owns is:

* Periodic tick (default 60s) that asks "any tasks due?"
* Per-task dispatch onto a worker thread pool (so several platforms can
  fan out without one slow ``fetch()`` blocking the others), gated by
  the existing per-platform :func:`slot` semaphore.
* Failure isolation — an adapter exception, a storage failure, or even
  a clock skew never kills the loop; the next tick still runs.
* Event fan-out — every state transition (started, finished, alert,
  failed) is pushed to a caller-supplied sink so the SSE bus can stream
  them to the UI.

The loop is intentionally not async: ``curl_cffi``/``DrissionPage``
adapters are blocking and we want them off the event loop driving
FastAPI. APScheduler's ``BackgroundScheduler`` runs jobs on its own
thread pool and plays nicely with FastAPI's async stack.
"""
from __future__ import annotations

import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal

from apscheduler.schedulers.background import BackgroundScheduler

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.notify import should_alert
from csm_core.monitor.platforms import ALL as ADAPTERS
from csm_core.monitor.rate_limit import slot
from csm_core.monitor.scheduler import select_due

logger = logging.getLogger(__name__)


EventKind = Literal[
    "started", "finished", "alert", "failed", "tick",
    "captcha_required", "captcha_resolved", "captcha_timeout",
]


@dataclass
class MonitorEvent:
    """One transition emitted from the loop. Carries enough context for the
    SSE bus to fan out to UI subscribers without re-querying the DB."""

    kind: EventKind
    task_id: int
    at: datetime
    result: MonitorResult | None = None
    error: str | None = None
    # For ``tick`` events only — count of tasks dispatched this tick.
    dispatched: int | None = None


EventSink = Callable[[MonitorEvent], None]


class MonitorLoop:
    """Background dispatcher for monitor tasks.

    Lifecycle:

        loop = MonitorLoop(event_sink=bus.publish, alert_top_n=5,
                           cooldown_hours=24, tick_seconds=60)
        loop.start()   # safe to call from FastAPI startup
        ...
        loop.stop()    # idempotent; safe from FastAPI shutdown

    Manual one-shot dispatch (for the "Run now" UI button) bypasses the
    schedule check but still goes through the same worker path —
    ``run_task_now(task_id)`` returns a :class:`concurrent.futures.Future`
    so the caller can ``await`` completion if desired.
    """

    def __init__(
        self,
        *,
        event_sink: EventSink,
        alert_top_n: int = 5,
        cooldown_hours: int = 24,
        tick_seconds: int = 60,
        max_workers: int = 4,
        adapters: dict[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._event_sink = event_sink
        self._alert_top_n = alert_top_n
        self._cooldown_hours = cooldown_hours
        self._tick_seconds = max(1, int(tick_seconds))
        # Adapters are injectable so tests can swap in fakes without
        # touching real curl_cffi / DrissionPage code paths.
        self._adapters = adapters if adapters is not None else dict(ADAPTERS)
        # Clock is injectable for the same reason: tests fast-forward
        # without sleeping for 60s.
        self._clock = clock or datetime.now

        self._scheduler: BackgroundScheduler | None = None
        self._executor: ThreadPoolExecutor | None = None
        # Guards against overlapping ticks — if a previous tick is still
        # iterating tasks when the next tick fires (clock skew, slow DB),
        # we skip rather than double-dispatch.
        self._tick_lock = threading.Lock()
        self._running = False

    # ── public lifecycle ────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="monitor-worker"
        )
        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=self._tick_seconds,
            id="monitor_tick",
            # Replace any leftover job from a previous run (defensive —
            # BackgroundScheduler is per-process, but if start() is ever
            # called twice without stop() this keeps us coherent).
            replace_existing=True,
            # If a tick takes longer than the interval, drop the
            # late one rather than queue it. We already have an
            # in-process lock for the same reason; this is the
            # APScheduler-level belt-and-braces.
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            "MonitorLoop started: tick=%ss, alert_top_n=%s, cooldown=%sh",
            self._tick_seconds,
            self._alert_top_n,
            self._cooldown_hours,
        )

    def stop(self, *, wait: bool = True) -> None:
        if not self._running:
            return
        self._running = False
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=wait)
            except Exception:
                logger.exception("scheduler shutdown raised; ignoring")
            self._scheduler = None
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)
            self._executor = None
        logger.info("MonitorLoop stopped")

    def is_running(self) -> bool:
        return self._running

    # ── manual dispatch (used by /api/monitor/run-now) ──────────────────
    def run_task_now(self, task_id: int) -> Future[MonitorResult | None]:
        """Force-dispatch a single task without consulting the schedule.

        Returns a Future resolving to the :class:`MonitorResult` (or
        ``None`` if the task was missing / disabled). Errors are emitted
        via the event sink and **also** raise into the future so callers
        with synchronous error handling don't have to subscribe.
        """
        if self._executor is None:
            raise RuntimeError("MonitorLoop is not started")
        return self._executor.submit(self._run_one_by_id, task_id)

    # ── tick / dispatch internals ───────────────────────────────────────
    def _tick(self) -> None:
        """One periodic sweep. Runs on APScheduler's own thread."""
        if not self._tick_lock.acquire(blocking=False):
            logger.warning("MonitorLoop tick overlap — previous tick still running, skipping")
            return
        try:
            now = self._clock()
            try:
                tasks = storage.list_tasks(enabled_only=True)
            except Exception:
                logger.exception("MonitorLoop: failed to list tasks; skipping tick")
                return
            due = select_due(tasks, now=now)
            self._publish(MonitorEvent(
                kind="tick", task_id=0, at=now, dispatched=len(due)
            ))
            if not due:
                return
            for task in due:
                if task.id is None:
                    continue
                # Fire-and-forget into the worker pool. Each worker
                # owns its own DB connection (storage uses threading.local),
                # so concurrent dispatch is safe.
                if self._executor is None:
                    return  # shutting down
                self._executor.submit(self._run_one, task)
        finally:
            self._tick_lock.release()

    def _run_one_by_id(self, task_id: int) -> MonitorResult | None:
        task = storage.get_task(task_id)
        if task is None:
            self._publish(MonitorEvent(
                kind="failed", task_id=task_id, at=self._clock(),
                error="task not found",
            ))
            return None
        if not task.enabled:
            self._publish(MonitorEvent(
                kind="failed", task_id=task_id, at=self._clock(),
                error="task disabled",
            ))
            return None
        return self._run_one(task)

    def _run_one(self, task: MonitorTask) -> MonitorResult | None:
        """Adapter dispatch + result persistence + alert decision.

        Mirrors the legacy :class:`csm_gui.workers.monitor_worker.MonitorWorker`
        contract verbatim — the only difference is event delivery (sink
        callback instead of pyqtSignal).
        """
        if task.id is None:
            return None
        adapter = self._adapters.get(task.type)
        if adapter is None:
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(),
                error=f"unknown task type: {task.type}",
            ))
            return None

        self._publish(MonitorEvent(
            kind="started", task_id=task.id, at=self._clock()
        ))

        try:
            with slot(task.type, timeout=120.0):
                result: MonitorResult = adapter.fetch(task)
        except TimeoutError as e:
            msg = f"timeout waiting for platform slot: {e}"
            logger.warning("monitor task %s: %s", task.id, msg)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(), error=msg,
            ))
            return None
        except Exception as e:  # noqa: BLE001 — worker boundary
            msg = f"{type(e).__name__}: {e}"
            logger.exception("monitor task %s adapter crashed", task.id)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(),
                error=f"{msg}\n{traceback.format_exc()}",
            ))
            return None

        # Decide alert before persistence so the alert flag and the row
        # land atomically. should_alert reads last_alert_at from storage.
        try:
            alert_now = should_alert(
                task, result,
                alert_top_n=self._alert_top_n,
                cooldown_hours=self._cooldown_hours,
            )
        except Exception:
            logger.exception("monitor task %s: should_alert raised; treating as no-alert", task.id)
            alert_now = False

        try:
            storage.save_result(result, alert_triggered=alert_now)
        except Exception as e:
            msg = f"persist failed: {e}"
            logger.exception("monitor task %s: %s", task.id, msg)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(), error=msg,
            ))
            return None

        self._publish(MonitorEvent(
            kind="finished", task_id=task.id, at=self._clock(), result=result,
        ))
        if alert_now:
            self._publish(MonitorEvent(
                kind="alert", task_id=task.id, at=self._clock(), result=result,
            ))
        return result

    def _publish(self, event: MonitorEvent) -> None:
        try:
            self._event_sink(event)
        except Exception:
            # Sink failure must NEVER kill the loop. SSE clients can
            # disconnect, queues can fill — log and move on.
            logger.exception("MonitorLoop event sink raised; dropping event %s", event.kind)
