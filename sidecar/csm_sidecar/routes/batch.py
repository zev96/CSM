"""Batch generation routes."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import batch_service

router = APIRouter(tags=["batch"], dependencies=[RequireToken])


class BatchBody(BaseModel):
    keywords: list[str] = Field(min_length=1)
    template_id: str = Field(min_length=1)
    skill_id: str | None = None
    seed: int = 0
    provider: str | None = None
    model: str | None = None
    skill_chain: list[str] | None = None
    candidates: int = Field(default=1, ge=1, le=3)
    contract_mode: Literal["conservative", "aggressive"] | None = None


class BatchAccepted(BaseModel):
    job_id: str
    stream_url: str
    total: int


@router.post("/api/batch", response_model=BatchAccepted, status_code=202)
def start_batch(body: BatchBody) -> BatchAccepted:
    """Submit a batch job. Subscribe to the SSE stream for live progress.

    Events emitted on ``/api/events/{job_id}``:
    - ``started``: ``total``, ``out_dir``
    - ``item_started``: ``index``, ``keyword``
    - ``item_finished``: ``index``, ``keyword``, ``status``,
      ``duration_seconds``, ``document``, ``error_*``, ``score``,
      ``score_parts``, ``candidate_scores``, ``factcheck_violations``
      (Phase 4+: 评分 + 多候选选优信号；旧字段位置不变)
    - ``cancel_requested``: when POST /api/batch/{id}/cancel is called
    - ``done``: ``total``, ``by_status``, ``total_duration_seconds``, ``total_cost``
    - ``error``: terminal failure outside the per-item loop
    """
    try:
        req = batch_service.BatchRequest(**body.model_dump())
        job_id = batch_service.submit(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state = batch_service.get_state(job_id)
    return BatchAccepted(
        job_id=job_id,
        stream_url=f"/api/events/{job_id}",
        total=len(state.keywords) if state else 0,
    )


@router.get("/api/batch/{job_id}")
def get_batch(job_id: str) -> dict[str, Any]:
    """Snapshot of the current batch state — for UI refresh / late join."""
    st = batch_service.get_state(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    return st.to_dict()


@router.post("/api/batch/{job_id}/cancel")
def cancel_batch(job_id: str) -> dict[str, Any]:
    """Cooperatively cancel a running batch.

    Already-running items finish; queued items are marked ``cancelled``.
    Calling on a finished or unknown job is a no-op (returns ``ok=False``)."""
    ok = batch_service.request_cancel(job_id)
    return {"job_id": job_id, "ok": ok}
