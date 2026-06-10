"""Article generation: POST /api/generate (job submit) + SSE stream."""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..auth import RequireToken
from ..event_bus import bus
from ..services import generate_service

router = APIRouter(tags=["generate"], dependencies=[RequireToken])


class GenerateBody(BaseModel):
    keyword: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    skill_id: str | None = None
    seed: int = 0
    draft_only: bool = False
    core_keyword: str | None = None
    provider: str | None = None
    model: str | None = None
    user_config: dict[str, int] | None = None


class JobAccepted(BaseModel):
    job_id: str
    stream_url: str


@router.post("/api/generate", response_model=JobAccepted, status_code=202)
def start_generate(body: GenerateBody) -> JobAccepted:
    """Kick off a generate job, return the SSE stream URL.

    The actual work runs on a worker thread; subscribe to the stream URL
    to receive progress events: ``stage`` (one per pipeline checkpoint),
    ``done`` (job complete with result payload), ``error`` (job failed).
    """
    req = generate_service.GenerateRequest(**body.model_dump())
    job_id = generate_service.submit(req)
    return JobAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")


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


@router.post("/api/generate/{job_id}/cancel")
def cancel_generate(job_id: str) -> dict:
    """Cooperatively cancel a running generate job.

    Already-finished / unknown job is a no-op (``ok=False``). The job
    terminates via an ``error`` SSE event carrying ``cancelled: true``.
    """
    ok = generate_service.request_cancel(job_id)
    return {"job_id": job_id, "ok": ok}
