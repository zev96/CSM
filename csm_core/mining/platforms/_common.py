"""Shared Protocol, helpers, and exceptions for mining platform adapters."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)

logger = logging.getLogger(__name__)


class RiskControlError(Exception):
    """Adapter saw a captcha/login wall mid-scrape."""


class NeedsLoginError(Exception):
    """Adapter found no valid login cookie at launch."""


OnCard = Callable[[VideoCard], None]
OnProgress = Callable[[ProgressUpdate], None]


class SearchAdapter(Protocol):
    """Each platform adapter implements this."""
    platform: Platform

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
        max_attempts: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> SearchOutcome:
        """Search the platform.

        Args:
          target_count: stop after emitting this many cards. Adapter may emit
                        more if a single page yields extras; runner is responsible
                        for cancel_event.
          max_attempts: max page-fetch attempts before bailing (anti-scrape).
                        None → adapter uses its own platform default from
                        csm_core.mining.config.get_max_attempts(self.platform).
          filters:      SearchFilters dump（按平台分组的 dict）。adapter 只读
                        自己平台那份；能下推的下推成请求参数，平台不支持的
                        （快手时间区间、抖音图文类型）在 emit 前本地过滤 ——
                        被过滤的卡不计入 emitted，翻页自然补偿产出。
                        None / 缺 key = 不筛，行为与旧签名完全一致。
        """
        ...


def date_to_epoch(date_str: str | None, *, end_of_day: bool = False) -> int | None:
    """Parse 'YYYY-MM-DD'（本地时区）into epoch seconds.

    end_of_day=True → 当天 23:59:59（闭区间的右端点）。无效/空输入返回 None。
    统一用本地时区：B 站下推参数和快手本地后过滤共用同一把尺子。
    """
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp())


def iso_within_epoch_range(
    published_at: str | None,
    begin_epoch: int | None,
    end_epoch: int | None,
) -> bool:
    """Check a stored ISO-UTC ``published_at`` against an epoch range.

    区间端点为 None = 不设限。published_at 缺失/解析失败时 **fail-open 返回
    True**：宁可多抓一条时间未知的视频，也不静默丢掉可能有效的候选。
    """
    if begin_epoch is None and end_epoch is None:
        return True
    if not published_at:
        return True
    try:
        ts = datetime.strptime(
            published_at.strip(), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return True
    if begin_epoch is not None and ts < begin_epoch:
        return False
    if end_epoch is not None and ts > end_epoch:
        return False
    return True


def parse_int_count(text: str) -> int | None:
    """Parse '1.2万' / '3.4k' / '5,678' / '' into int. Returns None on empty/invalid."""
    if not text:
        return None
    t = text.strip().replace(",", "").replace(" ", "")
    if not t:
        return None
    try:
        if t.endswith(("万", "w", "W")):
            return int(float(t[:-1]) * 10_000)
        if t.endswith(("亿",)):
            return int(float(t[:-1]) * 100_000_000)
        if t.endswith(("k", "K")):
            return int(float(t[:-1]) * 1_000)
        if t.endswith(("m", "M")):
            return int(float(t[:-1]) * 1_000_000)
        return int(float(t))
    except (ValueError, TypeError):
        return None


def parse_duration(text: str) -> int | None:
    """Parse '1:23' / '01:02:03' into seconds. Returns None on parse failure."""
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None
