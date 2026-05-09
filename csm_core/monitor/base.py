"""Core abstractions shared by every platform adapter.

The Protocol defined here is the contract every platform module under
``csm_core/monitor/platforms/`` must satisfy. Keeping the surface narrow
(one ``fetch`` call returning a dataclass) lets the scheduler and worker
treat all platforms uniformly while each adapter remains free to use
whatever fetcher (curl_cffi, DrissionPage, raw httpx) it needs.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from pydantic import BaseModel, Field


TaskType = Literal[
    "zhihu_question",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
]

MonitorStatus = Literal["ok", "failed", "risk_control", "skipped"]


class MonitorTask(BaseModel):
    """A scheduled monitor target.

    ``config_json`` is type-specific (target brand keyword for Zhihu,
    self-published comment text for the comment platforms). It is opaque
    to the scheduler; only the platform adapter interprets it.
    """

    id: int | None = None
    type: TaskType
    name: str
    target_url: str
    # Free-form per-type config. For ``zhihu_question`` this carries
    # ``{"target_brand": str, "top_n": int}``. For ``*_comment`` it carries
    # ``{"my_comment_text": str, "top_n": int}``. Keeping it as a generic
    # dict avoids a per-type subclass explosion at this layer.
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str = "manual"  # "HH:MM" for daily, or "manual"
    enabled: bool = True
    last_check_at: datetime | None = None
    last_status: MonitorStatus | None = None
    created_at: datetime | None = None


class MonitorResult(BaseModel):
    """One snapshot of a task's check.

    ``rank`` semantics differ by task type but the convention is the
    same: 1-based position of the user's target within the platform's
    Top-N list, or -1 when the target is absent. The scheduler uses this
    single field to decide whether to fire a rank-fell-out alert, which
    is why it lives at the top level rather than buried in metric_json.
    """

    task_id: int
    checked_at: datetime
    status: MonitorStatus
    rank: int = -1
    # Full snapshot (Top-N answers/comments, raw fields, similarity scores
    # for comment matching, etc). Stored as JSON in sqlite. Keep it
    # JSON-serializable — datetimes should be ISO strings, not datetime.
    metric: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""


@runtime_checkable
class BaseMonitorAdapter(Protocol):
    """Every platform module exports a singleton implementing this.

    Adapters MUST be safe to call from a worker QThread (no global Qt
    objects, no event-loop-bound primitives). They MAY block — the
    worker is what isolates them from the UI thread.
    """

    platform: TaskType

    def fetch(self, task: MonitorTask) -> MonitorResult:
        """Run one check. Should never raise — wrap exceptions into a
        ``MonitorResult(status='failed', error_message=...)`` so the
        worker can record the failure without special-casing."""
        ...
