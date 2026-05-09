"""Schedule decision (Qt-free).

The Qt side owns the QTimer + signal emission; this module owns the
"is task X due to run now?" question. Keeping that logic separate lets
unit tests cover scheduling without faking out a Qt event loop.

Schedule format (kept deliberately simple):

- ``"manual"`` — never fires automatically; only runs on user action.
- ``"HH:MM"`` — fires once per local day at the given wall-clock minute.

The scheduler considers a task due if its ``last_check_at`` is before
today's scheduled instant AND the current time has passed that instant.
"""
from __future__ import annotations
from datetime import datetime, time as dtime
from typing import Iterable

from .base import MonitorTask


def parse_schedule(schedule: str) -> dtime | None:
    """Return the ``HH:MM`` daily run time, or None for ``manual``."""
    schedule = (schedule or "").strip().lower()
    if not schedule or schedule == "manual":
        return None
    try:
        hh, mm = schedule.split(":", 1)
        return dtime(int(hh), int(mm))
    except (ValueError, IndexError):
        return None


def is_task_due(task: MonitorTask, now: datetime | None = None) -> bool:
    """True iff ``task`` should run at ``now`` (defaults to system clock)."""
    if not task.enabled:
        return False
    target = parse_schedule(task.schedule_cron)
    if target is None:
        return False  # manual tasks never fire from the scheduler

    now = now or datetime.now()
    today_at = datetime.combine(now.date(), target)
    if now < today_at:
        return False  # not yet today's scheduled instant
    last = task.last_check_at
    if last is None:
        return True
    # If the last check was strictly before today's scheduled instant,
    # we owe one run. Subsequent ticks past today_at remain a no-op
    # because last_check_at gets bumped to "now" on completion.
    return last < today_at


def select_due(tasks: Iterable[MonitorTask], now: datetime | None = None) -> list[MonitorTask]:
    """Filter ``tasks`` to those due to run at ``now``."""
    return [t for t in tasks if is_task_due(t, now=now)]
