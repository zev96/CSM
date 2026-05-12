"""Updater routes: check + download."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import updater_service

router = APIRouter(tags=["updater"], dependencies=[RequireToken])


@router.get("/api/updater/check")
async def check() -> dict[str, Any]:
    """Hit GitHub Releases for the latest manifest. Cheap (~2s) — sync."""
    return updater_service.check()


class DownloadBody(BaseModel):
    url: str = Field(min_length=1)
    expected_sha256: str = Field(min_length=64, max_length=64)


class DownloadAccepted(BaseModel):
    job_id: str
    stream_url: str


@router.post("/api/updater/download", response_model=DownloadAccepted, status_code=202)
async def download(body: DownloadBody) -> DownloadAccepted:
    """Stream-download an update asset. Subscribe to the SSE stream for
    progress (``progress`` events with ``done``/``total``/``percent``).

    On success: ``done`` event with ``target`` (local path) and ``sha256``.
    On failure: ``error`` event with the failure category.
    """
    job_id = updater_service.submit_download(
        url=body.url, expected_sha256=body.expected_sha256,
    )
    return DownloadAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")
