"""Monitor module: Zhihu question rank tracking + multi-platform comment retention.

This package is intentionally Qt-free. UI integration lives under
``csm_gui/pages/monitor_page.py`` and ``csm_gui/workers/monitor_worker.py``.
The core invariant: anything in here can be imported and exercised from
a plain CPython script without spinning up a QApplication.
"""
from .base import (
    BaseMonitorAdapter,
    MonitorTask,
    MonitorResult,
    MonitorStatus,
    TaskType,
)

__all__ = [
    "BaseMonitorAdapter",
    "MonitorTask",
    "MonitorResult",
    "MonitorStatus",
    "TaskType",
]
