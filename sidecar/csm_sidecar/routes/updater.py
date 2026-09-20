"""Updater routes: check + download + the generic ``/api/events`` SSE stream.

``GET /api/events/{job_id}`` used to live next to the article-generate
routes; the updater download (``useUpdateFlow.ts``) is now the only
caller of that stream (it follows ``stream_url`` returned by
``/api/updater/download``), so it lives here.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..auth import RequireToken
from ..event_bus import bus
from ..services import updater_service

router = APIRouter(tags=["updater"], dependencies=[RequireToken])


@router.get("/api/updater/check")
def check() -> dict[str, Any]:
    """Hit GitHub Releases for the latest manifest. Cheap (~2s) — sync."""
    return updater_service.check()


class DownloadBody(BaseModel):
    url: str = Field(min_length=1)
    expected_sha256: str = Field(min_length=64, max_length=64)


class DownloadAccepted(BaseModel):
    job_id: str
    stream_url: str


@router.post("/api/updater/download", response_model=DownloadAccepted, status_code=202)
def download(body: DownloadBody) -> DownloadAccepted:
    """Stream-download an update asset. Subscribe to the SSE stream for
    progress (``progress`` events with ``done``/``total``/``percent``).

    On success: ``done`` event with ``target`` (local path) and ``sha256``.
    On failure: ``error`` event with the failure category.
    """
    job_id = updater_service.submit_download(
        url=body.url, expected_sha256=body.expected_sha256,
    )
    return DownloadAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")


@router.get("/api/events/{job_id}")
async def stream_events(job_id: str):
    """Open an SSE stream for ``job_id``. See EventBus.stream for kinds."""
    async def _gen() -> AsyncIterator[dict]:
        async for event in bus.stream(job_id):
            yield {
                "event": event["kind"],
                "data": json.dumps(
                    {k: v for k, v in event.items() if k != "kind"},
                    ensure_ascii=False,
                ),
            }
    return EventSourceResponse(_gen())
