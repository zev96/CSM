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
# Aliased to underscore-prefix style matching local _CancelledFetch convention;
# no circular-import or name-clash reason.
from csm_core.monitor.drivers.risk_detector import RiskControlException as _RiskControlException
from csm_core.monitor.notify import should_alert
from csm_core.monitor.platforms import ALL as ADAPTERS
from csm_core.monitor.rate_limit import slot
from csm_core.monitor.scheduler import select_due
from csm_core.monitor.tikhub.client import balance_exhausted, reset_balance_latch

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
    "risk_control",  # Task 4: adapter hit risk control mid-scan; breakpoint saved
    # Native mode 方案 D：跑前等关 Chrome / Chrome 已关 / 命中风控需人工解
    "waiting_chrome_close", "chrome_closed", "needs_captcha",
    # 副本登录窗口关闭后的完成信号（专用事件，不再借用 needs_captcha —— 借用
    # 会让前端弹「需要人工解验证码（副本登录态已保存）」的错误提示）。
    "baidu_login_saved",
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
    # For ``risk_control`` events only — breakpoint position so the frontend
    # can render "已抓 N / 共 M · 从断点续抓" without digging into result.metric.
    last_resumed_keyword: int | None = None  # 0-indexed; next keyword to try on resume
    total_keywords: int | None = None        # full task keyword count
    # Native mode 方案 D 专用字段（默认 None，保持向后兼容）
    remaining_s: int | None = None  # waiting_chrome_close 倒计时
    keyword: str | None = None      # needs_captcha 的关键词文本
    kw_idx: int | None = None       # needs_captcha 的关键词索引 (0-based)


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
        api_adapters: dict[str, Any] | None = None,
        data_source_mode: str = "local",
        clock: Callable[[], datetime] | None = None,
        schedule_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._event_sink = event_sink
        self._alert_top_n = alert_top_n
        self._cooldown_hours = cooldown_hours
        self._tick_seconds = max(1, int(tick_seconds))
        # Adapters are injectable so tests can swap in fakes without
        # touching real curl_cffi / DrissionPage code paths.
        self._adapters = adapters if adapters is not None else dict(ADAPTERS)
        self._api_adapters = dict(api_adapters) if api_adapters else {}
        self._data_source_mode = data_source_mode
        # Clock is injectable for the same reason: tests fast-forward
        # without sleeping for 60s.
        # ⚠ 两个时钟，职责分离：
        #   _clock（UTC）：给所有 checked_at / event.at 时间戳打点。storage 把
        #     timestamp 当 UTC 存、序列化补 Z，csm_core 成功路径都用 utcnow；
        #     若改 local，失败路径 timestamp 比成功路径晚 8h（CST），
        #     ORDER BY checked_at DESC 会把 risk_control 排到 ok 后面。统一 UTC。
        #   _schedule_clock（本地）：给 select_due 判「到点没」。schedule_cron 是
        #     本地墙钟 HH:MM（用户按本地时间设 09:00），必须用本地时间比对，否则
        #     UTC 时钟会让 09:00 的任务在本地 17:00 才跑（CST 差 8h）。
        self._clock = clock or datetime.utcnow
        self._schedule_clock = schedule_clock or datetime.now

        self._scheduler: BackgroundScheduler | None = None
        self._executor: ThreadPoolExecutor | None = None
        # Guards against overlapping ticks — if a previous tick is still
        # iterating tasks when the next tick fires (clock skew, slow DB),
        # we skip rather than double-dispatch.
        self._tick_lock = threading.Lock()
        # 周期性清理过期 monitor_results（防无限膨胀；purge_old_results 此前 0
        # 调用）。24h 节流 + 保留 180 天；_last_purge_at 用 _clock（UTC）判间隔。
        self._last_purge_at: datetime | None = None
        self._purge_interval_s = 24 * 3600
        self._purge_keep_days = 180
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

    def set_data_source_mode(self, mode: str) -> None:
        """reconfigure() 在 config PATCH 后调用,热切数据源模式。"""
        self._data_source_mode = mode

    def set_alert_config(self, *, alert_top_n: int, cooldown_hours: int) -> None:
        """reconfigure() 在 config PATCH 后调用，热更告警阈值。原来 reconfigure
        只推 adapter 设置 + data_source_mode，漏了 loop 自己的 _alert_top_n /
        _cooldown_hours → 用户改「进入前 N 名才告警」「告警冷却」得重启才生效。"""
        self._alert_top_n = int(alert_top_n)
        self._cooldown_hours = int(cooldown_hours)

    def set_api_adapters(self, adapters: dict[str, Any]) -> None:
        self._api_adapters = dict(adapters or {})

    def _select_adapter(self, task_type: str):
        """API 模式且该 type 有 API 适配器 → 用 API;否则(含 baidu/geo)回落本地。"""
        if self._data_source_mode == "tikhub_api":
            api = self._api_adapters.get(task_type)
            if api is not None:
                return api
        return self._adapters.get(task_type)

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

    def has_active_baidu_task(self) -> bool:
        """Return True if any currently-active task is type=baidu_keyword.

        Used by routes/monitor.py reset-profile route to avoid corrupting
        a live persistent profile mid-write. Safe to call without callers
        holding _active_lock — we take a snapshot then resolve types via
        storage.
        """
        active_ids = self.get_active_task_ids()
        if not active_ids:
            return False
        for tid in active_ids:
            try:
                task = storage.get_task(tid)
            except Exception:
                continue
            if task is not None and task.type == "baidu_keyword":
                return True
        return False

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

    def _begin_dispatch(self, task_id: int) -> bool:
        """Atomically reserve ``task_id`` for dispatch iff it's not already
        running. Returns True if this call acquired the task (caller must
        dispatch and is responsible for :meth:`_untrack_active`), or False
        if the task is already active (caller must NOT dispatch).

        This is the single guard preventing the 60s scheduler tick from
        re-dispatching a still-running long task (a 93-keyword baidu run
        takes ~60-90 min, and ``last_check_at`` is only bumped on
        completion so ``select_due`` keeps returning it). It also blocks a
        manual «启动监测» / run-now from spinning a second concurrent
        worker on the same task. Seeds the cancel Event so a «停止» issued
        in the pre-register window before the worker starts isn't lost."""
        with self._active_lock:
            if task_id in self._active_task_ids:
                return False
            self._active_task_ids.add(task_id)
            if task_id not in self._cancel_events:
                self._cancel_events[task_id] = threading.Event()
            return True

    def is_task_active(self, task_id: int) -> bool:
        """True if ``task_id`` is currently reserved/running. Used by routes
        to 409 a duplicate run-now while a task is in flight."""
        with self._active_lock:
            return task_id in self._active_task_ids

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
        resume_from: int = 0,
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

        ``resume_from`` — 0-based keyword index to start from, used by
        POST /api/monitor/tasks/{id}/resume after a risk_control pause.
        Default 0 = normal full scan.
        """
        if self._executor is None:
            raise RuntimeError("MonitorLoop is not started")
        # Reserve the task atomically so /api/monitor/running reports it
        # the moment the POST returns, AND so a duplicate dispatch (a
        # second «启动监测» while the first run is still in flight, or a
        # cron tick that overlaps) is rejected rather than spinning a
        # second concurrent worker on the same task/profile.
        #
        # _begin_dispatch seeds the cancel Event, and the worker's
        # _track_active is idempotent, so cancel signals issued in this
        # pre-register window are not lost.
        if not self._begin_dispatch(task_id):
            logger.info(
                "run_task_now: task %s already running; ignoring duplicate dispatch",
                task_id,
            )
            done: Future[MonitorResult | None] = Future()
            done.set_result(None)
            return done
        try:
            return self._executor.submit(
                self._run_one_by_id_tracked, task_id,
                keyword_override=keyword_override,
                resume_from=resume_from,
            )
        except Exception:
            # If submit itself raises (e.g. pool shutting down), undo the
            # reservation so /running doesn't lie indefinitely.
            self._untrack_active(task_id)
            raise

    # ── tick / dispatch internals ───────────────────────────────────────
    def _maybe_purge_old_results(self) -> None:
        """24h 节流地清理过期 monitor_results。fail-soft：清理失败绝不影响派发。

        ``purge_old_results`` 此前全仓 0 调用 → DB 无限膨胀。这里在 tick 里
        节流触发（首次 tick 即跑一次，之后每 24h 一次），保留窗口 180 天。
        """
        now = self._clock()
        last = self._last_purge_at
        if last is not None and (now - last).total_seconds() < self._purge_interval_s:
            return
        self._last_purge_at = now
        try:
            deleted = storage.purge_old_results(keep_days=self._purge_keep_days)
            if deleted:
                logger.info(
                    "purged %d monitor_results older than %d days",
                    deleted, self._purge_keep_days,
                )
        except Exception:
            logger.exception("purge_old_results failed (non-fatal)")

    def _tick(self) -> None:
        """One periodic sweep. Runs on APScheduler's own thread."""
        reset_balance_latch()
        if not self._tick_lock.acquire(blocking=False):
            logger.warning("MonitorLoop tick overlap — previous tick still running, skipping")
            return
        try:
            # 周期性清理过期结果（24h 节流），放在 due 判定之前 —— 否则「无到点
            # 任务」的常见 tick 会走 `if not due: return` 早退，清理永远不跑。
            self._maybe_purge_old_results()
            # 到点判定用本地墙钟（schedule_cron 是本地 HH:MM）；事件时间戳仍用 UTC。
            now_local = self._schedule_clock()
            try:
                tasks = storage.list_tasks(enabled_only=True)
            except Exception:
                logger.exception("MonitorLoop: failed to list tasks; skipping tick")
                return
            due = select_due(tasks, now=now_local)
            self._publish(MonitorEvent(
                kind="tick", task_id=0, at=self._clock(), dispatched=len(due)
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
                # Skip tasks already in flight: a long task (93-keyword
                # baidu run ≈ 60-90 min) doesn't bump last_check_at until
                # it finishes, so select_due keeps returning it every tick.
                # Without this guard each tick would spin an extra full
                # scan (doubling risk-control exposure) and the duplicate
                # would race _untrack_active, breaking the «停止» button.
                if not self._begin_dispatch(task.id):
                    logger.debug(
                        "MonitorLoop: task %s still running; skip re-dispatch", task.id
                    )
                    continue
                try:
                    self._executor.submit(self._run_one_tracked, task)
                except Exception:
                    self._untrack_active(task.id)
                    raise
        finally:
            self._tick_lock.release()

    def _run_one_tracked(self, task: MonitorTask) -> MonitorResult | None:
        """Worker entry for scheduler dispatch. Guarantees the task is
        removed from the active set on EVERY exit path (including the
        early returns in _run_one that don't untrack), so a task reserved
        by _begin_dispatch is never leaked as permanently-running."""
        try:
            return self._run_one(task)
        finally:
            if task.id is not None:
                self._untrack_active(task.id)

    def _run_one_by_id_tracked(
        self,
        task_id: int,
        *,
        keyword_override: str | None = None,
        resume_from: int = 0,
    ) -> MonitorResult | None:
        """Worker entry for manual dispatch. Same untrack guarantee as
        :meth:`_run_one_tracked` — covers the task-missing / disabled
        early returns that otherwise leak a _begin_dispatch reservation."""
        try:
            return self._run_one_by_id(
                task_id,
                keyword_override=keyword_override,
                resume_from=resume_from,
            )
        finally:
            self._untrack_active(task_id)

    def _run_one_by_id(
        self,
        task_id: int,
        *,
        keyword_override: str | None = None,
        resume_from: int = 0,
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
        return self._run_one(task, resume_from=resume_from)

    def _run_one(
        self,
        task: MonitorTask,
        *,
        resume_from: int = 0,
    ) -> MonitorResult | None:
        """Adapter dispatch + result persistence + alert decision.

        Mirrors the legacy :class:`csm_gui.workers.monitor_worker.MonitorWorker`
        contract verbatim — the only difference is event delivery (sink
        callback instead of pyqtSignal).

        ``resume_from`` — 0-based keyword index to start from (baidu_keyword
        only). Default 0 = normal full scan. Passed down to the adapter so
        it can skip already-fetched keywords after a risk_control pause.
        """
        if task.id is None:
            return None
        adapter = self._select_adapter(task.type)
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

        def _dispatch_fetch() -> MonitorResult:
            # 4 级签名回退(老适配器没有 resume_from/cancel_token kwarg 时逐级降级)
            try:
                return adapter.fetch(
                    task, progress_cb=_progress_cb, cancel_token=cancel_token,
                    resume_from=resume_from,
                )
            except TypeError:
                try:
                    return adapter.fetch(
                        task, progress_cb=_progress_cb, cancel_token=cancel_token,
                    )
                except TypeError:
                    try:
                        return adapter.fetch(task, progress_cb=_progress_cb)
                    except TypeError:
                        return adapter.fetch(task)

        _is_api = (self._data_source_mode == "tikhub_api"
                   and task.type in self._api_adapters)
        try:
            if _is_api:
                # API 模式:①先查进程级余额闩,置位则本轮短路(不发请求、不刷屏)
                #           ②不进本地反爬 slot(TikHub 自己扛反爬,本地 5-15s pacing 无意义)
                if balance_exhausted():
                    self._publish(MonitorEvent(
                        kind="failed", task_id=task.id, at=self._clock(),
                        error="TikHub 余额不足,本轮跳过",
                    ))
                    self._untrack_active(task_id_local)
                    return None
                # TikHub 适配器签名统一(fetch(task, cancel_token=, progress_cb=, **_)),
                # 直接调一次,不走 4 级 TypeError 回退 —— 避免 fetch 体内偶发 TypeError
                # 触发重调 = 重复付费请求(§9:不自动重试)。
                result: MonitorResult = adapter.fetch(
                    task, progress_cb=_progress_cb, cancel_token=cancel_token,
                )
            else:
                with slot(task.type, timeout=120.0):
                    result = _dispatch_fetch()
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
        except _RiskControlException as e:
            # Task 4: risk control hit mid-scan. Save a breakpoint result so
            # POST /api/monitor/tasks/{id}/resume can restart from
            # last_resumed_keyword instead of keyword 0.
            #
            # Off-by-one 修正：e.progress = kw_idx 是「命中风控、尚未抓完」的那个
            # 关键词本身（raise 在 append 之前）。resume 必须从它重抓，所以
            # next_kw = progress，而不是历史上的 progress+1（那会把触发风控的
            # 关键词永久跳过，留下数据空洞）。progress=None（非定位型风控）→ 0。
            next_kw = e.progress if e.progress is not None else 0
            configured = list((task.config or {}).get("search_keywords", []))
            # 头段保全：把本轮已抓完的 partial（resume_from..next_kw-1）与上次断点
            # 保留的 [0..resume_from-1] 合并成完整头段 [0..next_kw-1]，写进断点
            # metric.keywords。否则风控中断会丢弃已抓数据，且 resume 期间再次
            # 中断会把更早的头段也丢掉。
            head_keywords = _merge_resumed_baidu_keywords(
                e.partial_keywords, resume_from, task.id, configured
            )
            err_msg = f"风控拦截：layer={e.signal.layer} detail={e.signal.detail}"
            logger.warning("monitor task %s: %s, saving breakpoint at %s", task.id, err_msg, next_kw)
            breakpoint_metric: dict[str, Any] = {
                "last_resumed_keyword": next_kw,
                "captcha_signal_layer": e.signal.layer,
                "captcha_signal_detail": e.signal.detail,
                "keywords": head_keywords,
                # total_keywords 保持完整 N（不是头段长度）→ 前端进度显示「3/10」。
                "total_keywords": len(configured),
                "search_keywords": configured,
                "target_brand": (task.config or {}).get("target_brand", ""),
            }
            breakpoint_metric.update(_baidu_keyword_aggregates(head_keywords))
            breakpoint_result = MonitorResult(
                task_id=task.id,
                checked_at=self._clock(),
                status="risk_control",
                rank=-1,
                metric=breakpoint_metric,
                error_message=err_msg,
            )
            try:
                storage.save_result(breakpoint_result, alert_triggered=False)
            except Exception:
                logger.exception("monitor task %s: failed to persist risk_control breakpoint", task.id)
            self._untrack_active(task_id_local)
            self._publish(MonitorEvent(
                kind="risk_control",
                task_id=task.id,
                at=self._clock(),
                error=err_msg,
                result=breakpoint_result,
                last_resumed_keyword=next_kw,
                total_keywords=len(task.config.get("search_keywords", [])),
            ))
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

        # Resume 失败保护：resume（resume_from>0）返回非 ok（尾段全失败 / 坏副本 /
        # 熔断）时，绝不能用失败结果覆盖断点 —— 否则断点里精心保全的头段从最新
        # 快照消失、且 last_resumed_keyword 丢失导致下次点续抓退化成从 0 全扫。
        # 失败成因常与断点同源（反爬/断网/坏 Chrome 副本），紧接的 resume 撞同样
        # 问题而全失败是很现实的路径。保留断点为最新，仅发 failed 事件让用户知道
        # 续抓失败、可稍后重试。（非 resume 的失败仍照常落库记录该次失败。）
        if resume_from > 0 and (not result or result.status != "ok"):
            reason = (result.error_message if result else None) or "续抓失败"
            logger.warning(
                "monitor task %s: resume returned %s; keeping breakpoint intact",
                task.id, (result.status if result else "None"),
            )
            self._untrack_active(task_id_local)
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(), error=reason,
            ))
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
        elif (
            resume_from > 0
            and task.type == "baidu_keyword"
            and result.status == "ok"
            and isinstance(result.metric, dict)
        ):
            # Resume 完成：适配器只抓了尾段 [resume_from:]。把它与上次断点
            # 保留的头段 [0:resume_from] 合并成完整 N 关键词快照，否则新 ok
            # 结果里只有尾段、头段永久缺失（0..resume_from-1 显示「从未监测」）。
            try:
                _merge_resumed_baidu_metric(
                    result, resume_from, task.id,
                    list((task.config or {}).get("search_keywords", [])),
                )
            except Exception:
                logger.exception(
                    "monitor task %s: resume-merge failed; persisting tail as-is",
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

        # Normal completion: drop from active set BEFORE publishing so any
        # frontend that listens and then immediately calls /running sees a
        # consistent (drained) view.
        self._untrack_active(task_id_local)
        if result.status == "ok":
            self._publish(MonitorEvent(
                kind="finished", task_id=task.id, at=self._clock(), result=result,
            ))
            if alert_now:
                self._publish(MonitorEvent(
                    kind="alert", task_id=task.id, at=self._clock(), result=result,
                ))
        else:
            # Adapter *returned* (did NOT raise) a non-ok result: circuit-breaker
            # open, config / native-mode validation error, or an adapter-level
            # "failed". Publishing these as `finished` is the bug behind «通知显示
            # 任务完成 + 界面未跑»: the frontend fires the «监测任务完成» bell on
            # every `finished`, while a non-ok result has no metric.keywords so the
            # Level-1 pill falls through to «未跑» with a bogus "keyword #0"
            # breakpoint — hiding the real failure. Surface as `failed` with the
            # real reason instead (see baidu_keyword breaker early-return + the
            # fetch() validation guards).
            self._publish(MonitorEvent(
                kind="failed", task_id=task.id, at=self._clock(),
                error=result.error_message or f"任务结束状态：{result.status}",
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
    # rank 列必须跟 metric 保持一致 —— should_alert 读的是 result.rank。只更
    # metric 不更 rank：单关键词未命中重跑会用「那一个词的 rank=-1」误触发
    # 任务级告警 + 24h 冷却压掉真告警，且 DB rank 列与 metric 永久 drift。
    result.rank = metric["best_default_first_rank"]
    # search_keywords should reflect the full task, not just the override
    metric["search_keywords"] = [kw.get("keyword") for kw in merged if kw.get("keyword")]


def _baidu_keyword_aggregates(keywords: "list[dict[str, Any]]") -> "dict[str, Any]":
    """Compute the count/rank aggregates over a baidu keyword-row list.

    Shared by the risk_control breakpoint save and the resume merge so the
    persisted ``matched_keywords`` / ``total_default_matches`` /
    ``best_default_first_rank`` stay consistent with what the adapter's own
    ``_fetch_once`` writes on a clean run.
    """
    matched = sum(1 for kw in keywords if (kw.get("default_first_rank") or 0) > 0)
    total_matches = sum(int(kw.get("default_matched_count") or 0) for kw in keywords)
    ranks = [
        int(kw.get("default_first_rank") or 0)
        for kw in keywords
        if (kw.get("default_first_rank") or 0) > 0
    ]
    return {
        "matched_keywords": matched,
        "total_default_matches": total_matches,
        "best_default_first_rank": min(ranks) if ranks else -1,
    }


def _merge_resumed_baidu_keywords(
    new_rows: "list[dict[str, Any]]",
    resume_from: int,
    task_id: int | None,
    configured_keywords: "list[str]",
) -> "list[dict[str, Any]]":
    """Splice freshly-scraped rows onto the head preserved in the prior breakpoint.

    ``new_rows`` covers ``keywords[resume_from:]`` (this run's slice). The
    head ``keywords[0:resume_from]`` lives in the most-recent stored result
    (the risk_control breakpoint that triggered this resume). We union the
    two by keyword string — **new rows win** (fresher) — and emit them in the
    task's configured order so no keyword is skipped or duplicated.

    ``resume_from <= 0`` (fresh full run) or no prior snapshot → returns
    ``new_rows`` unchanged. Mismatched/empty configured list → falls back to
    ``head + new`` concatenation so data is never dropped.

    Duplicate keywords (config anomaly): if ``configured_keywords`` lists the
    SAME keyword twice, each slot gets a distinct row object (2nd+ occurrences
    are shallow copies) so there's no aliasing; the count matches a fresh scan
    (which likewise produces one row per configured slot).
    """
    if resume_from <= 0 or task_id is None:
        return list(new_rows)
    prior_results = storage.list_results(task_id, limit=1)
    prior = prior_results[0] if prior_results else None
    head_rows: list[dict[str, Any]] = []
    if prior is not None and isinstance(prior.metric, dict):
        head_rows = prior.metric.get("keywords") or []

    by_kw: dict[str, dict[str, Any]] = {}
    for row in head_rows:
        kw = row.get("keyword")
        if kw is not None:
            by_kw[kw] = row
    for row in new_rows:
        kw = row.get("keyword")
        if kw is not None:
            by_kw[kw] = row  # fresher scrape overrides the preserved head

    # 按配置序发出；重复关键词的第 2+ 个槽发**浅拷贝**而非同一引用，避免 aliasing
    # （行数/顺序与全新扫描一致——配置里出现几次就几行）。
    merged: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for k in configured_keywords:
        row = by_kw.get(k)
        if row is None:
            continue
        seen[k] = seen.get(k, 0) + 1
        merged.append(row if seen[k] == 1 else dict(row))
    if not merged:
        # Configured list empty or fully mismatched — never drop data.
        return list(head_rows) + list(new_rows)
    return merged


def _merge_resumed_baidu_metric(
    result: MonitorResult,
    resume_from: int,
    task_id: int | None,
    configured_keywords: "list[str]",
) -> None:
    """Splice a resumed run's tail metric onto the prior breakpoint's head.

    The resumed adapter run only knows keywords ``[resume_from:]`` — every
    earlier keyword is absent from ``result.metric["keywords"]``. Reach into
    the most-recent stored result (the risk_control breakpoint), take its
    preserved head ``[0:resume_from]``, and rebuild the full ordered list so
    the persisted ok snapshot reflects every keyword the task tracks.

    Aggregates + ``result.rank`` are recomputed from the merged list.
    Mutates ``result.metric`` in-place. Deliberately does NOT set
    ``last_resumed_keyword`` — a completed resume is a clean snapshot, not a
    breakpoint; leaving it out means ``get_last_resumed_keyword`` returns None
    so a later resume click doesn't re-trigger from a stale position.
    """
    metric = result.metric
    if not isinstance(metric, dict):
        return
    tail = metric.get("keywords") or []
    merged = _merge_resumed_baidu_keywords(tail, resume_from, task_id, configured_keywords)
    metric["keywords"] = merged
    metric["total_keywords"] = len(merged)
    metric["search_keywords"] = [kw.get("keyword") for kw in merged if kw.get("keyword")]
    metric.update(_baidu_keyword_aggregates(merged))
    # rank 列必须跟 metric 一致 —— should_alert 读的是 result.rank。
    result.rank = metric["best_default_first_rank"]
