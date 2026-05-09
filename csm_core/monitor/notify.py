"""Alert decision logic — should this result fire a rank-fell-out alert?

Lives at the core layer (no Qt) so unit tests can exercise it without
spinning up a QApplication. The Qt side just calls
:func:`should_alert` for each fresh result and emits the appropriate
signal when it returns True.
"""
from __future__ import annotations
from datetime import datetime, timedelta

from . import storage
from .base import MonitorResult, MonitorTask


def should_alert(
    task: MonitorTask,
    result: MonitorResult,
    *,
    alert_top_n: int,
    cooldown_hours: int,
) -> bool:
    """Decide whether ``result`` should trigger a rank-fell-out alert.

    Three guards stack:

    1. Status must be ``ok`` — failures and risk-control hits don't
       trigger user-facing alerts (they show up in the task's last_status
       column instead, where the UI surfaces them differently).
    2. Rank must be outside Top-N (rank == -1, or rank > alert_top_n).
       A rank inside Top-N is a healthy signal, not an alert.
    3. We must be past the cooldown — without this, every scheduled tick
       would re-alert until the rank recovers, drowning the user.
    """
    if result.status != "ok":
        return False
    if 1 <= result.rank <= alert_top_n:
        return False
    if task.id is None:
        return False
    last = storage.last_alert_at(task.id)
    if last is None:
        return True
    cooldown = timedelta(hours=max(1, cooldown_hours))
    return (datetime.utcnow() - last) >= cooldown
