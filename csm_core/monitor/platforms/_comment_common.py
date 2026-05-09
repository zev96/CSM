"""Shared helpers for the three comment-retention adapters.

Bilibili, Douyin and Kuaishou all answer the same business question:
"is my self-published comment still in the hot list, and at what rank?"
The HTTP shape, signing scheme and pagination cursor differ per
platform — but everything downstream (cookie pick, pacing, breaker,
result construction, match-and-rank) is identical. Centralizing it here
keeps the three adapters thin and consistent.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Any

from ..base import MonitorResult, MonitorTask
from ..text_match import find_best_match, DEFAULT_SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)


def build_match_result(
    task: MonitorTask,
    comments: list[dict[str, Any]],
    source: str,
) -> MonitorResult:
    """Compute rank + similarity for the user's self-published comment."""
    my_text = (task.config.get("my_comment_text") or "").strip()
    top_n = int(task.config.get("top_n") or 10)
    threshold = float(task.config.get("threshold") or DEFAULT_SIMILARITY_THRESHOLD)

    if not my_text:
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="failed",
            rank=-1,
            error_message="task.config.my_comment_text is required",
        )

    # Slice to top_n hot comments before matching — the user only cares
    # whether they're in the hot list, not whether they appear somewhere
    # in the long tail of all comments.
    hot_slice = [c for c in comments if c.get("rank", -1) > 0][:top_n]
    match = find_best_match(my_text, hot_slice, threshold)

    rank = match["rank"] if match["found"] else -1
    return MonitorResult(
        task_id=task.id or 0,
        checked_at=datetime.utcnow(),
        status="ok",
        rank=rank,
        metric={
            "source": source,
            "my_comment_text": my_text,
            "top_n": top_n,
            "threshold": threshold,
            "matched": match["found"],
            "matched_text": match["matched_text"],
            "similarity": match["similarity"],
            "hot_comments": hot_slice,
            "total_fetched": len(comments),
        },
    )


def fail_result(task: MonitorTask, source: str, error_message: str) -> MonitorResult:
    return MonitorResult(
        task_id=task.id or 0,
        checked_at=datetime.utcnow(),
        status="failed",
        rank=-1,
        error_message=error_message,
        metric={"source": source},
    )


def risk_control_result(task: MonitorTask, source: str) -> MonitorResult:
    return MonitorResult(
        task_id=task.id or 0,
        checked_at=datetime.utcnow(),
        status="risk_control",
        rank=-1,
        error_message="risk control detected",
        metric={"source": source},
    )
