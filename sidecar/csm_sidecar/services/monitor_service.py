"""Read/write helpers for monitor tasks, results, credentials.

Wraps :mod:`csm_core.monitor.storage` so route handlers stay thin and
serialization (datetime → ISO, MonitorTask → dict) lives in one place.

Aggregation endpoints (summary / reports) are implemented here too —
they don't belong in csm_core because they're UI-shaped views, not core
business logic.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorStatus, MonitorTask, TaskType

PLATFORM_TYPES: tuple[TaskType, ...] = (
    "zhihu_question",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
)


# ── Task CRUD ──────────────────────────────────────────────────────────────
def task_to_dict(t: MonitorTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "type": t.type,
        "name": t.name,
        "target_url": t.target_url,
        "config": t.config,
        "schedule_cron": t.schedule_cron,
        "enabled": t.enabled,
        "last_check_at": t.last_check_at.isoformat() if t.last_check_at else None,
        "last_status": t.last_status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def list_tasks(type: TaskType | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
    return [task_to_dict(t) for t in storage.list_tasks(type=type, enabled_only=enabled_only)]


def get_task(task_id: int) -> dict[str, Any] | None:
    t = storage.get_task(task_id)
    return task_to_dict(t) if t else None


def create_task(task: MonitorTask) -> int:
    return storage.create_task(task)


def update_task(task: MonitorTask) -> None:
    storage.update_task(task)


def delete_task(task_id: int) -> None:
    storage.delete_task(task_id)


# ── Results ────────────────────────────────────────────────────────────────
def result_to_dict(r: MonitorResult) -> dict[str, Any]:
    return {
        "task_id": r.task_id,
        "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        "status": r.status,
        "rank": r.rank,
        "metric": r.metric,
        "error_message": r.error_message,
    }


def list_results(task_id: int, limit: int = 30) -> list[dict[str, Any]]:
    return [result_to_dict(r) for r in storage.list_results(task_id, limit=limit)]


def latest_result(task_id: int) -> dict[str, Any] | None:
    r = storage.latest_result(task_id)
    return result_to_dict(r) if r else None


# ── Credentials (cookie pool) ──────────────────────────────────────────────
def list_cookies(platform: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    """Return cookie metadata for ``platform``. Never returns the raw
    ``cookies_text`` — that's still in the row but we strip it so
    'who's logged in?' UIs can render without exposing actual cookies."""
    rows = storage.list_credentials(platform, enabled_only=enabled_only)
    return [_safe_cred(r) for r in rows]


def _safe_cred(row: dict[str, Any]) -> dict[str, Any]:
    """Project a credential row into the JSON shape the UI consumes.

    Strips ``cookies_text`` + ``user_agent`` (sensitive — once stored
    we never echo them back to the frontend, full stop). Computes
    ``cooldown_seconds_remaining`` and a derived ``status`` so the UI
    can render badges without re-deriving the same logic in JS.
    """
    import time as _time
    from csm_core.monitor.drivers.cookie_store import (
        AUTO_DISABLE_FAIL_COUNT, COOLDOWN_FAIL_THRESHOLD,
    )

    now = int(_time.time())
    cooldown_until = int(row.get("cooldown_until") or 0)
    cooldown_remaining = max(0, cooldown_until - now)
    fail_count = int(row["fail_count"])
    enabled = bool(row["enabled"])

    # Derive a single status string for UI pill rendering. Priority:
    # disabled > cooldown > stale > ok. "stale" means the cookie is
    # accumulating failures but hasn't hit the auto-disable threshold
    # yet — UI suggests "重新登录" while still letting the user opt to
    # keep trying.
    if not enabled:
        status = "disabled"
    elif cooldown_remaining > 0:
        status = "cooldown"
    elif fail_count >= COOLDOWN_FAIL_THRESHOLD:
        # >=3 consecutive failures = likely server-side dead (or zhihu
        # risk-control flagged this token). User should re-login via
        # the built-in browser flow.
        status = "stale"
    else:
        status = "ok"

    return {
        "id": row["id"],
        "platform": row["platform"],
        "label": row["label"],
        "enabled": enabled,
        "last_used_at": row.get("last_used_at"),
        "fail_count": fail_count,
        "created_at": row.get("created_at"),
        "cooldown_until": cooldown_until,
        "cooldown_seconds_remaining": cooldown_remaining,
        "status": status,
        "auto_disable_threshold": AUTO_DISABLE_FAIL_COUNT,
        # NB: cookies_text + user_agent intentionally omitted.
    }


def add_cookie(*, platform: str, cookies_text: str, label: str = "", user_agent: str = "") -> int:
    return storage.add_credential(
        platform=platform, cookies_text=cookies_text,
        label=label, user_agent=user_agent,
    )


def delete_cookie(cred_id: int) -> None:
    storage.delete_credential(cred_id)


# ── Summary (home + monitor screen) ────────────────────────────────────────
def get_summary() -> dict[str, Any]:
    """Per-platform overview: task count + each task's latest snapshot.

    Frontend renders 留存率 / 排名 visualisations from this. We don't
    aggregate the metric numerics here because the metric shape varies by
    platform — UI does the platform-aware unpacking it needs."""
    out: dict[str, Any] = {"platforms": {}, "generated_at": datetime.now().isoformat()}
    for ttype in PLATFORM_TYPES:
        tasks = storage.list_tasks(type=ttype)
        platform_view: dict[str, Any] = {"task_count": len(tasks), "tasks": []}
        for t in tasks:
            if t.id is None:
                continue
            latest = storage.latest_result(t.id)
            platform_view["tasks"].append({
                "id": t.id,
                "name": t.name,
                "target_url": t.target_url,
                "enabled": t.enabled,
                "latest": result_to_dict(latest) if latest else None,
            })
        out["platforms"][ttype] = platform_view
    return out


# ── Body validation helper used by routes ──────────────────────────────────
def storage_initialized() -> bool:
    """True if storage.init_db has been called for this process."""
    return storage._db_path is not None  # noqa: SLF001
