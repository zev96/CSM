"""Tests for the schedule decision logic."""
from __future__ import annotations
from datetime import datetime, timedelta, date, time as dtime

from csm_core.monitor.base import MonitorTask
from csm_core.monitor import scheduler
from csm_core.monitor.scheduler import is_task_due, parse_schedule, parse_weekly, select_due


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


class TestParseWeekly:
    def test_valid_returns_tuple(self):
        import datetime as _dt
        result = parse_weekly("weekly-3-14:30")
        assert result == (3, _dt.time(14, 30))

    def test_dow_out_of_range_returns_none(self):
        assert parse_weekly("weekly-7-09:00") is None

    def test_daily_format_returns_none(self):
        assert parse_weekly("09:00") is None

    def test_manual_returns_none(self):
        assert parse_weekly("manual") is None

    def test_none_input_returns_none(self):
        assert parse_weekly(None) is None  # type: ignore[arg-type]


def _wtask(cron, last=None):
    # geo_start_jitter_max=0 隔离启动抖动 —— 本组测通用周调度语义,不该被
    # geo 默认 20min 抖动缠上(抖动/窗口有独立测试组覆盖)。
    return MonitorTask(
        type="geo_query",
        name="t",
        target_url="geo://b",
        config={"brand": "b", "geo_start_jitter_max": 0},
        schedule_cron=cron,
        enabled=True,
        last_check_at=last,
    )


class TestWeeklySchedule:
    def test_weekly_due_on_matching_dow_after_time(self):
        # 2026-06-01 is a Monday (weekday 0)
        now = datetime(2026, 6, 1, 9, 30)
        assert is_task_due(_wtask("weekly-0-09:00"), now) is True

    def test_weekly_not_due_wrong_dow(self):
        # 2026-06-02 is a Tuesday (weekday 1), not Monday (0)
        now = datetime(2026, 6, 2, 9, 30)
        assert is_task_due(_wtask("weekly-0-09:00"), now) is False

    def test_weekly_not_due_before_time(self):
        # Monday 8:00 — before scheduled 9:00
        now = datetime(2026, 6, 1, 8, 0)
        assert is_task_due(_wtask("weekly-0-09:00"), now) is False

    def test_weekly_not_re_due_same_day(self):
        now = datetime(2026, 6, 1, 10, 0)
        last = datetime(2026, 6, 1, 9, 1)  # already checked today at 9:01
        assert is_task_due(_wtask("weekly-0-09:00", last), now) is False

    def test_weekly_due_no_last_check(self):
        # Monday, after time, no prior run
        now = datetime(2026, 6, 1, 9, 30)
        assert is_task_due(_wtask("weekly-0-09:00", None), now) is True


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


def _geo_task(*, id=42, cron="09:00", last=None, config=None):
    cfg = {"brand": "b"}
    if config:
        cfg.update(config)
    return MonitorTask(id=id, type="geo_query", name="t", target_url="geo://b",
                       config=cfg, schedule_cron=cron, enabled=True, last_check_at=last)


class TestStartJitterOffset:
    """确定性启动抖动偏移(§4.2):纯 per-day 种子,不读 now。"""

    def test_deterministic_same_task_same_day(self):
        a = scheduler._jitter_offset_seconds(7, date(2026, 5, 9), 20, dtime(9, 0))
        b = scheduler._jitter_offset_seconds(7, date(2026, 5, 9), 20, dtime(9, 0))
        assert a == b                      # 同 task+同日 → 稳定(跨 tick 不 flicker)

    def test_varies_across_days_and_tasks(self):
        d1 = scheduler._jitter_offset_seconds(7, date(2026, 5, 9), 20, dtime(9, 0))
        d2 = scheduler._jitter_offset_seconds(7, date(2026, 5, 10), 20, dtime(9, 0))
        t2 = scheduler._jitter_offset_seconds(8, date(2026, 5, 9), 20, dtime(9, 0))
        assert d1 != d2                    # 跨天变序(反周期指纹)
        assert d1 != t2                    # 不同任务错峰

    def test_bounded_by_max(self):
        for tid in range(200):
            off = scheduler._jitter_offset_seconds(tid, date(2026, 5, 9), 20, dtime(9, 0))
            assert 0 <= off <= 20 * 60     # ∈ [0, max]

    def test_zero_max_is_no_offset(self):
        assert scheduler._jitter_offset_seconds(7, date(2026, 5, 9), 0, dtime(9, 0)) == 0

    def test_clamps_near_midnight_no_cross_day(self):
        # target 23:55 + 20min 会跨午夜 → 夹到当日午夜前(299s = 到 23:59:59)。
        for tid in range(200):
            off = scheduler._jitter_offset_seconds(tid, date(2026, 5, 9), 20, dtime(23, 55))
            assert 0 <= off <= 299         # 绝不把实例推到次日


class TestStartJitterDue:
    def test_non_geo_task_no_jitter_fires_at_exact_target(self):
        # 类型门控:非 geo 任务偏移恒 0 → 到点即触发(逐字节等价旧行为)。
        task = MonitorTask(id=42, type="zhihu_question", name="t",
                           target_url="https://www.zhihu.com/question/1", config={},
                           schedule_cron="09:00", enabled=True, last_check_at=None)
        assert is_task_due(task, now=datetime(2026, 5, 9, 9, 0, 0)) is True

    def test_geo_task_delayed_by_deterministic_offset(self):
        task = _geo_task(id=42, cron="09:00")     # geo → 默认 20min 抖动
        off = scheduler._jitter_offset_seconds(42, date(2026, 5, 9), 20, dtime(9, 0))
        assert off > 0                             # 选定 id 确有非零偏移(证明抖动生效)
        jittered = datetime(2026, 5, 9, 9, 0, 0) + timedelta(seconds=off)
        # 抖动时刻前一秒:即便已过原始 09:00,也还没到抖动后时刻 → 不触发
        assert is_task_due(task, now=jittered - timedelta(seconds=1)) is False
        # 抖动时刻后:触发
        assert is_task_due(task, now=jittered + timedelta(seconds=1)) is True

    def test_geo_jitter_stable_across_ticks(self):
        # 同一天多次 tick(不同 now)判定必须一致地在抖动时刻翻转,不 flicker。
        task = _geo_task(id=99, cron="09:00")
        off = scheduler._jitter_offset_seconds(99, date(2026, 5, 9), 20, dtime(9, 0))
        jittered = datetime(2026, 5, 9, 9, 0, 0) + timedelta(seconds=off)
        # 抖动前的每一分钟都 False
        for m in range(0, off // 60):
            assert is_task_due(task, now=datetime(2026, 5, 9, 9, m, 0)) is False
        # 抖动后 True
        assert is_task_due(task, now=jittered + timedelta(seconds=30)) is True


class TestRunWindowGuard:
    def test_default_off_late_boot_still_fires(self):
        # 无 geo_run_window_hours → 迟到多久都补跑(向后兼容)。
        task = _geo_task(id=1, cron="09:00", config={"geo_start_jitter_max": 0})
        assert is_task_due(task, now=datetime(2026, 5, 9, 20, 0)) is True

    def test_window_skips_when_too_late(self):
        # 窗口 2h,开机在 09:00 后 5h → 跳过本周期(不补跑)。
        task = _geo_task(id=1, cron="09:00",
                         config={"geo_start_jitter_max": 0, "geo_run_window_hours": 2})
        assert is_task_due(task, now=datetime(2026, 5, 9, 14, 0)) is False

    def test_window_fires_when_within(self):
        # 窗口 6h,09:00 后 3h → 仍在窗内 → 触发。
        task = _geo_task(id=1, cron="09:00",
                         config={"geo_start_jitter_max": 0, "geo_run_window_hours": 6})
        assert is_task_due(task, now=datetime(2026, 5, 9, 12, 0)) is True

    def test_window_counts_from_jittered_instant(self):
        # 窗口从抖动后时刻起算:抖动 20min + 窗口 2h,现在 09:00 后 5h 仍超窗 → 跳过。
        task = _geo_task(id=42, cron="09:00", config={"geo_run_window_hours": 2})
        assert is_task_due(task, now=datetime(2026, 5, 9, 14, 30)) is False

    def test_invalid_window_treated_as_off(self):
        task = _geo_task(id=1, cron="09:00",
                         config={"geo_start_jitter_max": 0, "geo_run_window_hours": "abc"})
        assert is_task_due(task, now=datetime(2026, 5, 9, 20, 0)) is True
