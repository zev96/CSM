"""Schedule decision (Qt-free).

The Qt side owns the QTimer + signal emission; this module owns the
"is task X due to run now?" question. Keeping that logic separate lets
unit tests cover scheduling without faking out a Qt event loop.

Schedule format:

- ``"manual"`` — never fires automatically; only runs on user action.
- ``"HH:MM"`` — fires once per local day at the given wall-clock minute.
- ``"weekly-<dow>-<HH:MM>"`` — fires once per week on the given day-of-week
  (0=Monday … 6=Sunday, matching Python's ``datetime.weekday()``) at the
  given wall-clock time.

The scheduler considers a task due if its ``last_check_at`` is before
the current period's scheduled instant AND the current time has passed
that instant.
"""
from __future__ import annotations
import re
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


def parse_weekly(schedule: str) -> "tuple[int, dtime] | None":
    """Parse ``'weekly-<dow>-<HH:MM>'`` into ``(dow, time)``.

    ``dow`` is 0–6 following Python's ``datetime.weekday()`` convention
    (0=Monday, 6=Sunday). Returns None for daily strings, ``"manual"``,
    out-of-range dow (≥7), malformed input, or None input.
    """
    m = re.fullmatch(r"weekly-([0-6])-(\d{1,2}):(\d{2})", (schedule or "").strip().lower())
    if not m:
        return None
    dow, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if hh > 23 or mm > 59:
        return None
    return dow, dtime(hh, mm)


def _due_for_target(now: datetime, target: dtime, last: "datetime | None") -> bool:
    """True iff ``now`` has passed today's ``target`` time and ``last`` is stale."""
    today_at = datetime.combine(now.date(), target)
    if now < today_at:
        return False  # not yet today's scheduled instant
    if last is None:
        return True
    # If the last check was strictly before today's scheduled instant,
    # we owe one run. Subsequent ticks past today_at remain a no-op
    # because last_check_at gets bumped to "now" on completion.
    return last < today_at


def is_task_due(task: MonitorTask, now: datetime | None = None) -> bool:
    """True iff ``task`` should run at ``now`` (defaults to system clock)."""
    if not task.enabled:
        return False
    now = now or datetime.now()

    # Weekly path: "weekly-<dow>-<HH:MM>"
    wk = parse_weekly(task.schedule_cron)
    if wk is not None:
        dow, target = wk
        if now.weekday() != dow:
            return False
        return _due_for_target(now, target, task.last_check_at)

    # Daily path: "HH:MM" (or "manual" → None → False)
    target = parse_schedule(task.schedule_cron)
    if target is None:
        return False  # manual tasks never fire from the scheduler
    return _due_for_target(now, target, task.last_check_at)


def select_due(tasks: Iterable[MonitorTask], now: datetime | None = None) -> list[MonitorTask]:
    """Filter ``tasks`` to those due to run at ``now``."""
    return [t for t in tasks if is_task_due(t, now=now)]
