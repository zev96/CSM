"""Tests for the schedule decision logic."""
from __future__ import annotations
from datetime import datetime, timedelta

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.scheduler import is_task_due, parse_schedule, select_due


class TestParseSchedule:
    def test_manual_returns_none(self):
        assert parse_schedule("manual") is None
        assert parse_schedule("") is None
        assert parse_schedule(None) is None

    def test_hh_mm(self):
        t = parse_schedule("09:30")
        assert t is not None and t.hour == 9 and t.minute == 30

    def test_invalid_returns_none(self):
        assert parse_schedule("not-a-time") is None
        assert parse_schedule("25:00") is None  # invalid hour, no exception


class TestIsTaskDue:
    def _task(self, **kwargs) -> MonitorTask:
        defaults = dict(
            id=1,
            type="zhihu_question",
            name="t",
            target_url="https://www.zhihu.com/question/1",
            config={"target_brand": "x"},
            schedule_cron="09:00",
            enabled=True,
            last_check_at=None,
        )
        defaults.update(kwargs)
        return MonitorTask(**defaults)

    def test_disabled_never_due(self):
        now = datetime(2026, 5, 9, 10, 0)
        task = self._task(enabled=False)
        assert is_task_due(task, now=now) is False

    def test_manual_never_due(self):
        now = datetime(2026, 5, 9, 10, 0)
        task = self._task(schedule_cron="manual")
        assert is_task_due(task, now=now) is False

    def test_first_run_after_schedule_time_fires(self):
        now = datetime(2026, 5, 9, 9, 5)
        task = self._task(schedule_cron="09:00", last_check_at=None)
        assert is_task_due(task, now=now) is True

    def test_before_schedule_time_does_not_fire(self):
        now = datetime(2026, 5, 9, 8, 30)
        task = self._task(schedule_cron="09:00", last_check_at=None)
        assert is_task_due(task, now=now) is False

    def test_already_ran_today_does_not_re_fire(self):
        now = datetime(2026, 5, 9, 15, 0)
        task = self._task(
            schedule_cron="09:00",
            last_check_at=datetime(2026, 5, 9, 9, 1),
        )
        assert is_task_due(task, now=now) is False

    def test_yesterday_run_re_fires_today(self):
        now = datetime(2026, 5, 9, 9, 1)
        task = self._task(
            schedule_cron="09:00",
            last_check_at=datetime(2026, 5, 8, 9, 0),
        )
        assert is_task_due(task, now=now) is True


class TestSelectDue:
    def test_filters_only_due(self):
        now = datetime(2026, 5, 9, 9, 5)
        tasks = [
            MonitorTask(id=1, type="zhihu_question", name="a", target_url="https://www.zhihu.com/question/1",
                        config={}, schedule_cron="09:00", enabled=True, last_check_at=None),
            MonitorTask(id=2, type="zhihu_question", name="b", target_url="https://www.zhihu.com/question/2",
                        config={}, schedule_cron="manual", enabled=True),
            MonitorTask(id=3, type="zhihu_question", name="c", target_url="https://www.zhihu.com/question/3",
                        config={}, schedule_cron="20:00", enabled=True),
        ]
        due = select_due(tasks, now=now)
        assert [t.id for t in due] == [1]
