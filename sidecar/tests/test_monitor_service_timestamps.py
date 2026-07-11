"""Serialized monitor timestamps must carry an explicit UTC 'Z'.

Stored timestamps are naive UTC (storage writes Z-suffixed UTC, _parse_iso
strips the Z back to a naive value). If the API layer serializes them with a
bare ``.isoformat()`` (no Z), the frontend's ``new Date(...)`` parses them as
*local* time, shifting every displayed time and calendar-day bucket by the UTC
offset (8h in CST) — the day-bucketing bug behind Baidu/GEO trend charts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_sidecar.services import monitor_service


def test_result_to_dict_stamps_utc_z():
    r = MonitorResult(
        task_id=1,
        checked_at=datetime(2026, 7, 9, 22, 0, 0),
        status="ok",
        rank=1,
        metric={},
    )
    d = monitor_service.result_to_dict(r)
    assert d["checked_at"] == "2026-07-09T22:00:00Z"


def test_task_to_dict_stamps_utc_z():
    t = MonitorTask(
        type="baidu_keyword",
        name="x",
        target_url="u",
        config={},
        schedule_cron="manual",
        enabled=True,
    )
    t.last_check_at = datetime(2026, 7, 9, 22, 0, 0)
    t.created_at = datetime(2026, 7, 1, 1, 2, 3)
    d = monitor_service.task_to_dict(t)
    assert d["last_check_at"] == "2026-07-09T22:00:00Z"
    assert d["created_at"] == "2026-07-01T01:02:03Z"


def test_iso_utc_normalizes_aware_to_utc_z():
    aware = datetime(2026, 7, 9, 22, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert monitor_service._iso_utc(aware) == "2026-07-09T14:00:00Z"


def test_iso_utc_none_passthrough():
    assert monitor_service._iso_utc(None) is None
