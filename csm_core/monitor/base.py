"""Core abstractions shared by every platform adapter.

The Protocol defined here is the contract every platform module under
``csm_core/monitor/platforms/`` must satisfy. Keeping the surface narrow
(one ``fetch`` call returning a dataclass) lets the scheduler and worker
treat all platforms uniformly while each adapter remains free to use
whatever fetcher (curl_cffi, DrissionPage, raw httpx) it needs.
"""
from __future__ import annotations
import threading
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from pydantic import BaseModel, Field


def maybe_cancel(cancel_token: "threading.Event | None") -> None:
    """Co-operative cancellation checkpoint.

    Adapters call this at well-defined points in ``fetch()`` —— between
    network requests, between page batches, before heavy browser spin-up.
    If the user clicked 「停止」 via the UI, monitor_loop sets the event,
    and we raise the sidecar's ``_CancelledFetch`` exception (lazy-imported
    to avoid the csm_core → csm_sidecar circular dep).

    The exception is caught by ``MonitorLoop._run_one`` which emits a
    `failed` event with reason="cancelled by user", so the UI knows the
    user's stop click was actually honored mid-fetch (vs. zhihu/comment's
    previous behavior of running to completion regardless).

    No-op when cancel_token is None (legacy callers / unit tests).
    """
    if cancel_token is None or not cancel_token.is_set():
        return
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        # Running csm_core standalone (tests / scripts) — fall back to a
        # generic RuntimeError; the worker layer (which catches
        # _CancelledFetch by name) isn't present anyway.
        _CancelledFetch = RuntimeError  # type: ignore[assignment]
    raise _CancelledFetch("cancelled by user")


def is_cancelled(exc: BaseException) -> bool:
    """exc 是否为 maybe_cancel 抛的取消信号（sidecar 的 _CancelledFetch）。

    standalone（无 sidecar，maybe_cancel 退化抛 RuntimeError）时无从区分 → False。
    供 adapter / provider 的 except 区分「用户主动 Stop」与「真错误」：取消应上抛，
    不记 error、不打噪声 traceback。
    """
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        return False
    return isinstance(exc, _CancelledFetch)


TaskType = Literal[
    "zhihu_question",
    "zhihu_search",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
    "baidu_keyword",
    "geo_query",
]

MonitorStatus = Literal["ok", "failed", "risk_control", "skipped", "error"]


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
