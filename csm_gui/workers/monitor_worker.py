"""QThread worker that runs one monitor task off the UI thread.

The worker is intentionally generic across all platforms — the platform
adapter dispatch happens via ``platforms.ALL[task.type]``. That keeps
the Qt side from caring whether a task is a Zhihu rank check or a
Bilibili comment retention check, and lets every adapter be tested in
isolation from Qt.
"""
from __future__ import annotations
import logging
import traceback
from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.platforms import ALL as ADAPTERS
from csm_core.monitor.notify import should_alert
from csm_core.monitor.rate_limit import slot

logger = logging.getLogger(__name__)


class MonitorWorker(QThread):
    """Run a single :class:`MonitorTask`, emit a result.

    Signals
    -------
    started: int — task_id when work begins (UI shows a spinner)
    finished: object — :class:`MonitorResult` after a successful run
    failed: int, str — task_id + error message on unhandled exception
    alert: int, object — task_id + result when the rank-fell-out
        cooldown allows a fresh alert
    """

    started = pyqtSignal(int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(int, str)
    alert = pyqtSignal(int, object)

    def __init__(
        self,
        task: MonitorTask,
        *,
        alert_top_n: int,
        cooldown_hours: int,
        parent=None,
    ):
        super().__init__(parent)
        self._task = task
        self._alert_top_n = alert_top_n
        self._cooldown_hours = cooldown_hours

    def run(self) -> None:  # type: ignore[override]
        task = self._task
        if task.id is None:
            self.failed.emit(0, "task.id is required")
            return
        adapter = ADAPTERS.get(task.type)
        if adapter is None:
            self.failed.emit(task.id, f"unknown task type: {task.type}")
            return

        self.started.emit(task.id)
        try:
            # Bound concurrent in-flight against the platform's slot
            # semaphore so e.g. five Zhihu tasks scheduled at the same
            # time don't stampede the same domain.
            with slot(task.type, timeout=120.0):
                result: MonitorResult = adapter.fetch(task)
        except TimeoutError as e:
            logger.warning("monitor worker timed out waiting for slot: %s", e)
            self.failed.emit(task.id, f"timeout waiting for platform slot: {e}")
            return
        except Exception as e:  # noqa: BLE001 — worker boundary
            logger.exception("monitor worker crashed")
            self.failed.emit(task.id, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            return

        # Decide alert BEFORE writing — the alert flag goes onto the
        # same row, and we want save_result + last_alert_at to stay
        # consistent. should_alert reads last_alert_at via storage, so
        # the decision is correct as long as we save in one shot below.
        alert_now = should_alert(
            task,
            result,
            alert_top_n=self._alert_top_n,
            cooldown_hours=self._cooldown_hours,
        )
        try:
            storage.save_result(result, alert_triggered=alert_now)
        except Exception as e:
            logger.exception("failed to persist monitor result")
            self.failed.emit(task.id, f"persist failed: {e}")
            return

        self.finished.emit(result)
        if alert_now:
            self.alert.emit(task.id, result)
