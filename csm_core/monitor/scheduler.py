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
import hashlib
import re
from datetime import datetime, time as dtime, timedelta
from typing import Iterable

from .base import MonitorTask

# 启动抖动的 per-type 默认(分钟)。只有 GEO 会按固定时刻驱动 3 个有头浏览器,
# 固定时刻 + 固定顺序 + 零阅读 = 周期性机器人指纹;故只有 GEO 给非零默认。
# 其余任务类型偏移恒 0 → 调度逐字节不变,绝不回归 baidu/zhihu/comment。
# 任务可用 config["geo_start_jitter_max"] 覆盖(含设 0 关闭)。
_START_JITTER_DEFAULT_MIN: dict[str, int] = {"geo_query": 20}
_JITTER_MAX_CAP_MIN = 120   # 上限护栏(防配置误填天文数字把任务推到明天)


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


def _jitter_max_min(task: MonitorTask) -> int:
    """本任务的启动抖动上限(分钟)。config 覆盖 per-type 默认;非法值回落默认。"""
    default = _START_JITTER_DEFAULT_MIN.get(task.type, 0)
    raw = (task.config or {}).get("geo_start_jitter_max", default)
    try:
        return max(0, min(int(raw), _JITTER_MAX_CAP_MIN))
    except (TypeError, ValueError):
        return default


def _run_window_hours(task: MonitorTask) -> "float | None":
    """迟到守卫窗口(小时)。默认 None=关(opt-in);<=0 或非法 → None。

    设了则:任务过了(抖动后的)预定时刻超过 window 小时仍没跑 → 本周期跳过
    (等下一周期),避免关机/睡眠后开机把错过的任务瞬间全速补跑。"""
    raw = (task.config or {}).get("geo_run_window_hours")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _jitter_offset_seconds(task_id: int, day, jitter_max_min: int, target: dtime) -> int:
    """确定性启动延迟(秒)∈ [0, max]。**forward-only**(只延后,是「启动延迟」)。

    两条不变量:
    - **确定性种子**:只依赖 (task_id, 当日),不读 ``now``。否则每次 tick 重算
      不同偏移 → 到点判定 flicker(任务可能永不触发或乱触发)。用 sha256 而非
      ``hash()``——后者被 PYTHONHASHSEED 随机化,跨进程/tick 变值。
    - **clamp 同日**:上限夹到「target 到当日午夜前」。否则近午夜的 target(如
      23:55)抖过午夜 → 该实例是在 day N 算出的 day N+1 时刻,第二天用的却是
      day N+1 自己的 target,该实例永不被看见 → 当天漏跑。
    """
    if jitter_max_min <= 0:
        return 0
    secs_to_midnight = 86400 - (target.hour * 3600 + target.minute * 60 + target.second) - 1
    max_sec = max(0, min(jitter_max_min * 60, secs_to_midnight))
    if max_sec <= 0:
        return 0
    key = f"{task_id}:{day.isoformat()}:start_jitter".encode()
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return seed % (max_sec + 1)


def _due_for_target(now: datetime, target: dtime, last: "datetime | None",
                    task: "MonitorTask | None" = None) -> bool:
    """True iff ``now`` has passed today's ``target`` time and ``last`` is stale.

    当 ``task`` 提供时,叠加两项 §4.2 调度节奏(纯 per-day 确定性,跨 tick 稳定):
    启动抖动把 today_at 向后推随机 0–N 分钟;run-window 守卫在迟到过久时跳过。
    """
    today_at = datetime.combine(now.date(), target)
    if task is not None:
        jmax = _jitter_max_min(task)
        if jmax > 0:
            today_at += timedelta(
                seconds=_jitter_offset_seconds(task.id or 0, now.date(), jmax, target))
    if now < today_at:
        return False  # 未到(抖动后的)今日预定时刻
    # run-window 守卫:开机/唤醒太晚 → 本周期跳过,避免迟到全速补跑风暴。
    # 放在 last 判定之前:漏跑(last is None/stale)也照样被窗口挡下。
    if task is not None:
        win = _run_window_hours(task)
        if win is not None and (now - today_at) > timedelta(hours=win):
            return False
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
        return _due_for_target(now, target, task.last_check_at, task)

    # Daily path: "HH:MM" (or "manual" → None → False)
    target = parse_schedule(task.schedule_cron)
    if target is None:
        return False  # manual tasks never fire from the scheduler
    return _due_for_target(now, target, task.last_check_at, task)


def select_due(tasks: Iterable[MonitorTask], now: datetime | None = None) -> list[MonitorTask]:
    """Filter ``tasks`` to those due to run at ``now``."""
    return [t for t in tasks if is_task_due(t, now=now)]
