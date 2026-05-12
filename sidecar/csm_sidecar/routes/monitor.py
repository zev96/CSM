"""Monitor module routes — tasks, results, cookies, summary, reports, events."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from csm_core.monitor.base import MonitorTask, TaskType

from ..auth import RequireToken
from ..monitor_bus import monitor_bus
from ..services import monitor_lifecycle, monitor_service

router = APIRouter(tags=["monitor"], dependencies=[RequireToken])


def _require_storage() -> None:
    if not monitor_service.storage_initialized():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="monitor storage not initialised — call POST /api/monitor/init or start the sidecar in production mode",
        )


# ── Task CRUD ──────────────────────────────────────────────────────────────
class TaskBody(BaseModel):
    """POST/PATCH body. ``id`` is server-assigned on create."""
    type: TaskType
    name: str = Field(min_length=1)
    target_url: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str = "manual"
    enabled: bool = True


@router.get("/api/monitor/tasks")
async def list_tasks(
    type: TaskType | None = Query(default=None),
    enabled_only: bool = Query(default=False),
) -> dict[str, Any]:
    _require_storage()
    items = monitor_service.list_tasks(type=type, enabled_only=enabled_only)
    return {"count": len(items), "tasks": items}


@router.get("/api/monitor/tasks/{task_id}")
async def get_task(task_id: int) -> dict[str, Any]:
    _require_storage()
    t = monitor_service.get_task(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return t


@router.post("/api/monitor/tasks", status_code=201)
async def create_task(body: TaskBody) -> dict[str, Any]:
    _require_storage()
    task = MonitorTask(**body.model_dump())
    new_id = monitor_service.create_task(task)
    return monitor_service.get_task(new_id) or {"id": new_id}


@router.patch("/api/monitor/tasks/{task_id}")
async def update_task(task_id: int, body: TaskBody) -> dict[str, Any]:
    _require_storage()
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    task = MonitorTask(id=task_id, **body.model_dump())
    monitor_service.update_task(task)
    return monitor_service.get_task(task_id) or {}


@router.delete("/api/monitor/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int) -> None:
    _require_storage()
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    monitor_service.delete_task(task_id)


@router.post("/api/monitor/tasks/{task_id}/run-now")
async def run_now(task_id: int) -> dict[str, Any]:
    """Force one dispatch off-schedule. Returns immediately — watch
    /api/monitor/events for the result."""
    _require_storage()
    loop = monitor_lifecycle.get()
    if loop is None or not loop.is_running():
        raise HTTPException(
            status_code=503,
            detail="MonitorLoop not running — start the sidecar in production mode",
        )
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    loop.run_task_now(task_id)
    return {"task_id": task_id, "queued": True}


# ── Results ────────────────────────────────────────────────────────────────
@router.get("/api/monitor/results")
async def list_results(
    task_id: int = Query(...),
    limit: int = Query(default=30, ge=1, le=500),
) -> dict[str, Any]:
    """Historical results — feeds the sparkline (D in A2 alignment table)."""
    _require_storage()
    rows = monitor_service.list_results(task_id, limit=limit)
    return {"task_id": task_id, "count": len(rows), "results": rows}


# ── Cookies ────────────────────────────────────────────────────────────────
class CookieBody(BaseModel):
    cookies_text: str = Field(min_length=1)
    label: str = ""
    user_agent: str = ""


@router.get("/api/monitor/cookies")
async def list_cookies(
    platform: str = Query(...),
    enabled_only: bool = Query(default=False),
) -> dict[str, Any]:
    _require_storage()
    rows = monitor_service.list_cookies(platform, enabled_only=enabled_only)
    return {"platform": platform, "count": len(rows), "cookies": rows}


@router.post("/api/monitor/cookies/{platform}", status_code=201)
async def add_cookie(platform: str, body: CookieBody) -> dict[str, Any]:
    _require_storage()
    cred_id = monitor_service.add_cookie(platform=platform, **body.model_dump())
    return {"id": cred_id, "platform": platform, "label": body.label}


@router.delete("/api/monitor/cookies/{cred_id}", status_code=204)
async def delete_cookie(cred_id: int) -> None:
    _require_storage()
    monitor_service.delete_cookie(cred_id)


# ── Summary + reports ──────────────────────────────────────────────────────
@router.get("/api/monitor/summary")
async def get_summary() -> dict[str, Any]:
    _require_storage()
    return monitor_service.get_summary()


@router.get("/api/monitor/reports")
async def get_reports(
    period: str = Query(default="daily"),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, Any]:
    _require_storage()
    try:
        return monitor_service.get_reports(period=period, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── Live event stream ──────────────────────────────────────────────────────
@router.get("/api/monitor/events")
async def stream_events():
    """SSE broadcast of every MonitorLoop event. Multiple clients OK."""
    async def _gen() -> AsyncIterator[dict]:
        async for event in monitor_bus.subscribe():
            yield {
                "event": event["kind"],
                "data": json.dumps(
                    {k: v for k, v in event.items() if k != "kind"},
                    ensure_ascii=False,
                ),
            }
    return EventSourceResponse(_gen())
