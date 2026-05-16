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


class _CancelledFetch(Exception):
    """Raised by an adapter when its cooperative ``cancel_token`` was set
    by the user via POST /api/monitor/tasks/{id}/cancel. Caught by
    :meth:`MonitorLoop._run_one` which then emits a `failed` event with
    a clear «cancelled by user» reason."""


EventKind = Literal[
    "started", "finished", "alert", "failed", "tick",
    "captcha_required", "captcha_resolved", "captcha_timeout",
    "progress",
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
    # For ``progress`` events only — fine-grained "N of M" updates during
    # adapter.fetch(). Baidu's keyword loop publishes after each keyword;
    # UI shows progress bar `current / total`.
    progress_current: int | None = None
    progress_total: int | None = None


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
        # ── Active-task tracking (truth source for "what's running") ──
        # Frontend uses /api/monitor/running to hydrate UI state when a
        # component remounts after the user navigated away. Adapter loops
        # check `_cancel_events[task_id].is_set()` between keywords for
        # cooperative cancellation. Lock guards both maps because they're
        # read from FastAPI request threads and mutated by worker threads.
        self._active_lock = threading.Lock()
        self._active_task_ids: set[int] = set()
        self._cancel_events: dict[int, threading.Event] = {}
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

    # ── active-task introspection / cancellation ────────────────────────
    def get_active_task_ids(self) -> list[int]:
        """Snapshot of task_ids currently in-flight on a worker thread.

        Frontend GET /api/monitor/running hydrates UI state from this so
        components show the correct «监测中…» / progress bar after the
        user navigates away and comes back. Sorted for stable response.
        """
        with self._active_lock:
            return sorted(self._active_task_ids)

    def cancel_task(self, task_id: int) -> bool:
        """Signal the worker thread for ``task_id`` to bail out at its
        next cooperative check point. Returns True if a cancel signal
        was delivered (task was running), False otherwise.

        Adapters honor this between unit-of-work boundaries (e.g. baidu
        checks between keywords). The worker eventually raises
        :class:`CancelledError` which :func:`_run_one` catches and
        publishes as a `failed` event with error="cancelled by user".
        """
        with self._active_lock:
            ev = self._cancel_events.get(task_id)
            if ev is None:
                return False
            ev.set()
            return True

    def _track_active(self, task_id: int) -> threading.Event:
        """Start tracking. Returns the per-task cancel Event the worker
        should poll. Idempotent under the lock —- safe even if the same
        task is somehow dispatched twice (shouldn't happen with the
        existing slot semaphore, but defensive)."""
        with self._active_lock:
            self._active_task_ids.add(task_id)
            ev = self._cancel_events.get(task_id)
            if ev is None:
                ev = threading.Event()
                self._cancel_events[task_id] = ev
            return ev

    def _untrack_active(self, task_id: int) -> None:
        with self._active_lock:
            self._active_task_ids.discard(task_id)
            self._cancel_events.pop(task_id, None)

    # ── manual dispatch (used by /api/monitor/run-now) ──────────────────
    def run_task_now(
        self,
        task_id: int,
        *,
        keyword_override: str | None = None,
    ) -> Future[MonitorResult | None]:
        """Force-dispatch a single task without consulting the schedule.

        Returns a Future resolving to the :class:`MonitorResult` (or
        ``None`` if the task was missing / disabled). Errors are emitted
        via the event sink and **also** raise into the future so callers
        with synchronous error handling don't have to subscribe.

        ``keyword_override`` — when set (and the task is a baidu_keyword
        task), only that single keyword's SERP is scraped, and the
        partial result is merged with the most-recent stored snapshot so
        the other keywords' data is not lost. Used by the Level 2
        «启动监测» button.
        """
        if self._executor is None:
            raise RuntimeError("MonitorLoop is not started")
        return self._executor.submit(
            self._run_one_by_id, task_id, keyword_override=keyword_override,
        )

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

    def _run_one_by_id(
        self,
        task_id: int,
        *,
        keyword_override: str | None = None,
    ) -> MonitorResult | None:
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
        # Stamp the in-memory task config with the override so the
        # adapter scrapes only this keyword. _run_one will detect the
        # marker and merge with the previous snapshot before persisting.
        if keyword_override and task.type == "baidu_keyword":
            cfg = dict(task.config or {})
            cfg["search_keywords"] = [keyword_override]
            cfg["_keyword_override"] = keyword_override
            task.config = cfg
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

        # Track this task as active so /api/monitor/running can report
        # it; cancel_token is the Event the adapter polls.
        task_id_local = task.id
        cancel_token = self._track_active(task_id_local)

        # Progress callback (Baidu adapter uses it; other adapters ignore
        # the kwarg via **kwargs catch-all). Captured task.id so the SSE
        # event carries it correctly even if the adapter forgets.
        def _progress_cb(current: int, total: int) -> None:
            try:
                self._publish(MonitorEvent(
                    kind="progress",
                    task_id=task_id_local,
                    at=self._clock(),
                    progress_current=int(current),
                    progress_total=int(total),
                ))
            except Exception:
                logger.exception("progress event publish failed (task %s)", task_id_local)

        try:
            with slot(task.type, timeout=120.0):
                # Try the new signature first (with cancel_token + progress_cb);
                # fall back progressively for adapters that haven't been
                # upgraded yet. TypeError tells us the kwarg is unknown.
                try:
                    result: MonitorResult = adapter.fetch(
                        task, progress_cb=_progress_cb, cancel_token=cancel_token,
                    )
                except TypeError:
                    try:
                        result = adapter.fetch(task, progress_cb=_progress_cb)
                    except TypeError:
                        result = adapter.fetch(task)
        except _CancelledFetch as e:
            # Cooperative cancellation: adapter saw cancel_token set and
            # bailed out cleanly. Publish a failed event with a clear
            # reason so the UI knows the user's «停止» click was honored.
            msg = "cancelled by user"
            logger.info("monitor task %s: %s (%s)", task.id, msg, e)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(), error=msg,
            ))
            self._untrack_active(task_id_local)
            return None
        except TimeoutError as e:
            msg = f"timeout waiting for platform slot: {e}"
            logger.warning("monitor task %s: %s", task.id, msg)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(), error=msg,
            ))
            self._untrack_active(task_id_local)
            return None
        except Exception as e:  # noqa: BLE001 — worker boundary
            msg = f"{type(e).__name__}: {e}"
            logger.exception("monitor task %s adapter crashed", task.id)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(),
                error=f"{msg}\n{traceback.format_exc()}",
            ))
            self._untrack_active(task_id_local)
            return None

        # Single-keyword override merge: if the user fired «启动监测» from
        # the Level 2 page, the adapter only scraped one keyword. Pull
        # the previous full snapshot and splice the new keyword's row
        # in, so the persisted metric still reflects the latest state of
        # every keyword the task tracks.
        override_kw = (task.config or {}).get("_keyword_override")
        if override_kw and result.metric and isinstance(result.metric, dict):
            try:
                _merge_partial_baidu_metric(result, override_kw, task.id)
            except Exception:
                logger.exception(
                    "monitor task %s: keyword-merge failed; persisting partial as-is",
                    task.id,
                )

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
            self._untrack_active(task_id_local)
            return None

        # Normal completion: drop from active set BEFORE publishing finished
        # so any frontend that listens to finished and then immediately
        # calls /running sees a consistent (drained) view.
        self._untrack_active(task_id_local)
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


def _merge_partial_baidu_metric(
    result: MonitorResult,
    override_kw: str,
    task_id: int | None,
) -> None:
    """Splice a single-keyword ``result.metric`` into the prior snapshot.

    The baidu adapter's per-keyword run only knows about ``override_kw``
    — every other keyword in ``result.metric["keywords"]`` is absent.
    To keep the Level 2 left list and the aggregated KPIs honest after
    a one-keyword «启动监测», we reach into the most recent stored
    result, take its ``keywords`` list, and replace the matching row
    with the freshly-scraped data. Aggregates (``total_*`` etc.) are
    recomputed from the merged list.

    No-ops cleanly if there is no prior snapshot, if the prior snapshot
    has no metric, or if ``result.metric`` lacks the expected shape.
    All mutation happens in-place on ``result.metric``.
    """
    if task_id is None:
        return
    metric = result.metric
    if not isinstance(metric, dict):
        return
    new_keywords = metric.get("keywords") or []
    if not new_keywords:
        return
    new_kw_row = next(
        (kw for kw in new_keywords if kw.get("keyword") == override_kw),
        None,
    )
    if new_kw_row is None:
        return

    prior_results = storage.list_results(task_id, limit=1)
    prior = prior_results[0] if prior_results else None
    if prior is None or not isinstance(prior.metric, dict):
        # No prior snapshot — leave the partial result alone; the user
        # will see only the keyword they ran. That's expected for the
        # first invocation.
        return
    prior_kws = prior.metric.get("keywords") or []
    if not prior_kws:
        return

    merged: list[dict[str, Any]] = []
    replaced = False
    for prev_kw_row in prior_kws:
        if prev_kw_row.get("keyword") == override_kw:
            merged.append(new_kw_row)
            replaced = True
        else:
            merged.append(prev_kw_row)
    if not replaced:
        # Override keyword wasn't in the prior snapshot (e.g. user added
        # it via task edit between runs) — append it so it shows up.
        merged.append(new_kw_row)

    metric["keywords"] = merged
    metric["total_keywords"] = len(merged)
    metric["matched_keywords"] = sum(
        1 for kw in merged if (kw.get("default_first_rank") or 0) > 0
    )
    metric["total_default_matches"] = sum(
        int(kw.get("default_matched_count") or 0) for kw in merged
    )
    ranks = [
        int(kw.get("default_first_rank") or 0)
        for kw in merged
        if (kw.get("default_first_rank") or 0) > 0
    ]
    metric["best_default_first_rank"] = min(ranks) if ranks else -1
    # search_keywords should reflect the full task, not just the override
    metric["search_keywords"] = [kw.get("keyword") for kw in merged if kw.get("keyword")]
