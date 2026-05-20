"""Dedup + keyword density routes."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import dedup_service, keyword_service

router = APIRouter(tags=["dedup"], dependencies=[RequireToken])


# ── /api/dedup/build-index ──────────────────────────────────────────────────
class BuildIndexBody(BaseModel):
    kind: Literal["history", "vault"]


class BuildIndexAccepted(BaseModel):
    job_id: str
    stream_url: str


@router.post("/api/dedup/build-index", response_model=BuildIndexAccepted, status_code=202)
def build_index(body: BuildIndexBody) -> BuildIndexAccepted:
    """Kick off an index rebuild. Subscribe to the SSE stream for progress.

    Events:
    - ``progress``: ``done``, ``total``, ``percent``
    - ``done``: ``kind``, ``doc_count``
    - ``error``: ``error``
    """
    job_id = dedup_service.submit_build(body.kind)
    return BuildIndexAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")


# ── /api/dedup/analyze ──────────────────────────────────────────────────────
class AnalyzeBody(BaseModel):
    text: str = Field(min_length=1)
    kind: Literal["history", "vault"] = "history"


@router.post("/api/dedup/analyze")
def analyze(body: AnalyzeBody) -> dict[str, Any]:
    """Run a duplicate-rate check against the named index.

    If no index is loaded for ``kind`` (never built, or load failed),
    returns the standard "empty report" shape rather than 404 so the
    article 质检报告 UI renders identically in either case.
    """
    return dedup_service.analyze(body.text, body.kind)


# ── /api/dedup/status ───────────────────────────────────────────────────────
@router.get("/api/dedup/status")
def status() -> dict[str, Any]:
    """Doc counts per kind — feeds the settings 历史查重 panel."""
    return dedup_service.index_status()


# ── /api/keyword/density ────────────────────────────────────────────────────
class DensityBody(BaseModel):
    keyword: str = Field(min_length=1)
    text: str = Field(min_length=1)


@router.post("/api/keyword/density")
def keyword_density(body: DensityBody) -> dict[str, Any]:
    return keyword_service.density(keyword=body.keyword, text=body.text)
