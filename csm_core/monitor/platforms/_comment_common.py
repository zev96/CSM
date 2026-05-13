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


#: 实际比对扫描范围 —— adapters 一般抓 ~200 条 hot 评论，再深没意义。
#: 用户填的 top_n 是"理想排名上限"（默认 5），跟这个扫描范围是两回事，
#: 之前混用导致 rank=20 的评论被 [:15] 切掉永远找不到。
DEFAULT_SCRAPE_TOP_N = 150


def build_match_result(
    task: MonitorTask,
    comments: list[dict[str, Any]],
    source: str,
) -> MonitorResult:
    """Compute rank + similarity for the user's self-published comment.

    ``rank`` semantics: 1-based actual position within the first
    ``scrape_top_n`` hot comments, or -1 when the comment falls beyond
    that scope / can't be matched at all. The user-facing ``alert_top_n``
    is just an ideal threshold for the UI to color-code "in ideal range"
    vs "fell out of ideal"; it does NOT clip the search window.
    """
    my_text = (task.config.get("my_comment_text") or "").strip()
    # 用户填的 top_n 现在严格解读为"理想排名"：希望评论出现在前 N 位。
    # 默认 5。命中且 rank <= alert_top_n → 在理想范围，UI 显绿。
    alert_top_n = int(task.config.get("top_n") or 5)
    # 实际扫描范围，可由 task.config 覆盖（不公开开关），默认 150。
    # 让 rank=20、rank=80 的评论也能被找到并展示实际位置。
    scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
    threshold = float(task.config.get("threshold") or DEFAULT_SIMILARITY_THRESHOLD)

    if not my_text:
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="failed",
            rank=-1,
            error_message="task.config.my_comment_text is required",
        )

    # 全量扫描前 scrape_top_n 条；命中即返回真实位置（≥1），不再因为
    # 用户 alert_top_n 设置就强行切窄。adapter 抓得太少时（< scrape_top_n）
    # 也按实际抓到的算，metric.scope_total 会记录真实扫描了多少条。
    hot_slice = [c for c in comments if c.get("rank", -1) > 0][:scrape_top_n]
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
            "alert_top_n": alert_top_n,
            "scrape_top_n": scrape_top_n,
            # 实际比对的条数（小于 scrape_top_n 表示评论区没那么多 hot 评论）
            "scope_total": len(hot_slice),
            "threshold": threshold,
            "matched": match["found"],
            "matched_text": match["matched_text"],
            "similarity": match["similarity"],
            # hot_comments 全留着，前端"抢占者"挑前几条用
            "hot_comments": hot_slice,
            "total_fetched": len(comments),
            # 兼容字段：旧前端代码读 top_n 当作 alert 阈值时仍能工作
            "top_n": alert_top_n,
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
