"""Shared Protocol, helpers, and exceptions for mining platform adapters."""
from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol

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
    ) -> SearchOutcome: ...


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
