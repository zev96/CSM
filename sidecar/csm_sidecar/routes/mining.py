"""Mining module routes — jobs, videos, login flow, SSE events."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from csm_core.browser_infra import mining_browser
from csm_core.mining import storage as mining_storage
from csm_core.mining.models import Platform, StartJobRequest

from ..auth import RequireToken
from ..event_bus import bus as event_bus
from ..services import mining_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mining"], dependencies=[RequireToken])


# ── Jobs ─────────────────────────────────────────────────────────────
@router.post("/api/mining/jobs", status_code=201)
async def start_job(body: StartJobRequest) -> dict[str, Any]:
    try:
        job_id = mining_service.submit_job(
            keyword=body.keyword,
            platforms=body.platforms,
            target_per_platform=body.target_per_platform,
        )
    except RuntimeError as e:
        if "busy" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    job = mining_storage.get_job(job_id)
    return {"job_id": job_id, "status": "pending", "job": job}


@router.get("/api/mining/jobs")
async def list_jobs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    items = mining_storage.list_jobs(limit=limit)
    return {"count": len(items), "jobs": items}


@router.get("/api/mining/jobs/{job_id}")
async def get_job(job_id: int) -> dict[str, Any]:
    job = mining_storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return job


@router.post("/api/mining/jobs/{job_id}/cancel")
async def cancel(job_id: int) -> dict[str, Any]:
    ok = mining_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="job not running or already finished")
    return {"job_id": job_id, "cancelled": True}


@router.get("/api/mining/jobs/{job_id}/events")
async def stream_events(job_id: int):
    """SSE stream of mining.* events for one job."""
    queue_key = f"mining-{job_id}"

    async def event_gen():
        async for event in event_bus.stream(queue_key):
            yield {"event": event.get("kind", "message"), "data": _json(event)}

    return EventSourceResponse(event_gen())


def _json(obj: Any) -> str:
    import json as _j
    return _j.dumps(obj, ensure_ascii=False, default=str)


# ── Videos ───────────────────────────────────────────────────────────
@router.get("/api/mining/videos/export.csv")
async def export_csv(
    keyword: str | None = Query(default=None),
    platform: Platform | None = Query(default=None),
    commented: str = Query(default="0", pattern="^(0|1|all)$"),
    q: str | None = Query(default=None),
):
    rows, _ = mining_storage.list_videos(
        keyword=keyword, platform=platform, commented=commented,
        q=q, offset=0, limit=10_000,
    )
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel auto-detects UTF-8
    writer = csv.writer(buf)
    writer.writerow([
        "platform", "video_id", "url", "title", "author",
        "duration_sec", "play_count", "like_count",
        "source_keywords", "already_commented", "first_seen_at",
    ])
    for r in rows:
        writer.writerow([
            r["platform"], r["platform_video_id"], r["url"], r["title"],
            r["author_name"], r["duration_sec"] or "",
            r["play_count"] or "", r["like_count"] or "",
            "|".join(r["source_keywords"]),
            "1" if r["already_commented"] else "0",
            r["first_seen_at"],
        ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mining_videos.csv"'},
    )


@router.get("/api/mining/videos")
async def list_videos(
    keyword: str | None = Query(default=None),
    platform: Platform | None = Query(default=None),
    commented: str = Query(default="0", pattern="^(0|1|all)$"),
    q: str | None = Query(default=None),
    job_id: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    rows, total = mining_storage.list_videos(
        keyword=keyword, platform=platform, commented=commented,
        q=q, job_id=job_id, offset=offset, limit=limit,
    )
    return {"total": total, "offset": offset, "limit": limit, "videos": rows}


@router.delete("/api/mining/videos/{video_id}", status_code=204)
async def soft_delete_video(video_id: int) -> None:
    if not mining_storage.soft_delete_video(video_id):
        raise HTTPException(status_code=404, detail="video not found")


# ── Login ────────────────────────────────────────────────────────────
class LoginStartBody(BaseModel):
    platform: Platform


_login_specs = {
    "douyin": ("https://www.douyin.com/", "sessionid"),
    "bilibili": ("https://www.bilibili.com/", "SESSDATA"),
    "kuaishou": ("https://www.kuaishou.com/", "kuaishou.web.cp.api_st"),
}


@router.get("/api/mining/login/status")
async def login_status() -> dict[str, Any]:
    return {
        platform: {"logged_in": mining_browser.has_login_cookie(platform)}
        for platform in _login_specs
    }


@router.post("/api/mining/login/{platform}")
async def login_start(platform: Platform) -> dict[str, Any]:
    """Launch a headed Patchright window pointing at the platform homepage.

    User logs in manually; cookies persist in the platform's user_data_dir.
    Returns immediately — the browser stays open and is closed when the
    user calls /confirm.
    """
    import threading
    state = _login_state
    with state.lock:
        if state.active_platform is not None:
            raise HTTPException(status_code=409, detail=f"login already active for {state.active_platform}")
        state.active_platform = platform
        state.confirm_event = threading.Event()

    def _runner():
        try:
            url, cookie_name = _login_specs[platform]
            with mining_browser.launched_page(platform, headless=False) as page:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                logger.info("login flow opened for %s — waiting up to 10 min for /confirm", platform)
                state.confirm_event.wait(timeout=600)
        except Exception as e:
            logger.exception("login flow for %s crashed: %s", platform, e)
        finally:
            with state.lock:
                state.active_platform = None
                state.confirm_event = None

    threading.Thread(target=_runner, name=f"mining-login-{platform}", daemon=True).start()
    return {"platform": platform, "browser_opened": True}


@router.post("/api/mining/login/{platform}/confirm")
async def login_confirm(platform: Platform) -> dict[str, Any]:
    state = _login_state
    with state.lock:
        if state.active_platform != platform or state.confirm_event is None:
            raise HTTPException(status_code=409, detail="no active login flow")
        state.confirm_event.set()
    import time
    for _ in range(20):
        with state.lock:
            if state.active_platform is None:
                break
        time.sleep(0.1)
    logged_in = mining_browser.has_login_cookie(platform)
    return {"platform": platform, "logged_in": logged_in}


class _LoginState:
    def __init__(self) -> None:
        import threading
        self.lock = threading.Lock()
        self.active_platform: Platform | None = None
        self.confirm_event: threading.Event | None = None


_login_state = _LoginState()
