"""Qt-facing controller: schedules monitor tasks and dispatches workers.

Owns:
- A QTimer that ticks every ``TICK_SECONDS`` and asks the core
  ``scheduler.select_due`` for any tasks ready to run.
- A small registry of in-flight :class:`MonitorWorker` instances so the
  same task can't be queued twice (the user clicking "Run now" while
  the periodic tick has already fired the same task is the obvious
  case).
- Forwarded signals: ``task_started`` / ``task_finished`` /
  ``task_failed`` / ``task_alert`` for the UI page to consume without
  knowing about per-worker plumbing.

Why a controller and not just inline-in-page wiring: monitor work runs
even when the user is on a different page (e.g. ArticlePage), so the
scheduler must outlive the MonitorPage instance. Putting it on
MainWindow as a controller mirrors how ``ArticleController`` and
``BatchController`` already behave.
"""
from __future__ import annotations
import logging
from datetime import datetime
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from csm_core.monitor import scheduler as core_scheduler
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.rate_limit import (
    configure_concurrency,
    configure_pacing,
    get_breaker,
)
from csm_gui.config import AppConfig
from csm_gui.workers.monitor_worker import MonitorWorker

logger = logging.getLogger(__name__)

TICK_SECONDS = 60


class MonitorController(QObject):
    """High-level façade for monitor work, owned by MainWindow."""

    task_started = pyqtSignal(int)
    task_finished = pyqtSignal(object)  # MonitorResult
    task_failed = pyqtSignal(int, str)
    task_alert = pyqtSignal(int, object)  # task_id, MonitorResult
    scheduling_changed = pyqtSignal(bool)

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._workers: dict[int, MonitorWorker] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_SECONDS * 1000)
        self._timer.timeout.connect(self._on_tick)
        # Apply any initial config to the rate-limit knobs so the
        # adapters running on the first manual fetch already see the
        # user's settings.
        self.apply_config(config)

    # ── Public API ─────────────────────────────────────────────────────────
    def apply_config(self, config: AppConfig) -> None:
        """Update rate-limit / concurrency / pacing from the config."""
        self._config = config
        m = config.monitor
        for platform in (
            "zhihu_question",
            "bilibili_comment",
            "douyin_comment",
            "kuaishou_comment",
        ):
            configure_concurrency(platform, m.concurrency_per_platform)
            configure_pacing(platform, m.request_delay_min, m.request_delay_max)

    def start_scheduling(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            logger.info("MonitorController: scheduler started (tick=%ds)", TICK_SECONDS)
            self.scheduling_changed.emit(True)
            # Tick once immediately so freshly-due tasks don't have to
            # wait a whole minute when the user enables scheduling.
            self._on_tick()

    def stop_scheduling(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            logger.info("MonitorController: scheduler stopped")
            self.scheduling_changed.emit(False)

    def is_scheduling(self) -> bool:
        return self._timer.isActive()

    def run_now(self, task_id: int) -> bool:
        """Kick off a one-off run of ``task_id``. Returns False if the
        task is already in-flight (the UI typically disables the button
        in that case but a guard here keeps the contract safe)."""
        if task_id in self._workers:
            return False
        task = storage.get_task(task_id)
        if task is None:
            logger.warning("run_now: task %d not found", task_id)
            return False
        return self._spawn_worker(task)

    # ── Internal ───────────────────────────────────────────────────────────
    def _on_tick(self) -> None:
        try:
            tasks = storage.list_tasks(enabled_only=True)
        except Exception:
            logger.exception("scheduler tick: list_tasks failed")
            return
        due = core_scheduler.select_due(tasks, now=datetime.now())
        for task in due:
            if task.id in self._workers:
                continue
            # The platform's circuit breaker is the cleaner place to
            # gate "should we even try right now" — workers also check
            # this, but skipping here saves a thread spin-up.
            if not get_breaker(task.type).allow():
                logger.info("breaker open for %s; skipping task %s", task.type, task.id)
                continue
            self._spawn_worker(task)

    def _spawn_worker(self, task: MonitorTask) -> bool:
        if task.id is None:
            return False
        m = self._config.monitor
        worker = MonitorWorker(
            task,
            alert_top_n=m.alert_top_n,
            cooldown_hours=m.alert_cooldown_hours,
            parent=self,
        )
        worker.started.connect(self.task_started.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.alert.connect(self.task_alert.emit)
        # QThread.finished cleans up the registry slot whatever the
        # outcome, so a crashed worker can't strand a permanently busy
        # task_id.
        worker.finished.connect(lambda *_: self._cleanup_worker(task.id))
        worker.failed.connect(lambda *_: self._cleanup_worker(task.id))
        self._workers[task.id] = worker
        worker.start()
        return True

    def _cleanup_worker(self, task_id: int | None) -> None:
        if task_id is None:
            return
        self._workers.pop(task_id, None)

    def _on_worker_finished(self, result: MonitorResult) -> None:
        self.task_finished.emit(result)

    def _on_worker_failed(self, task_id: int, message: str) -> None:
        self.task_failed.emit(task_id, message)
