"""Article generation: POST /api/generate (job submit) + SSE stream."""
from __future__ import annotations

import json
from typing import AsyncIterator, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from csm_core.angle import Angle

from ..auth import RequireToken
from ..event_bus import bus
from ..services import assembler_service, factcheck_service, generate_service

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
    # Phase 2a：标题领衔 + 角度选材（都为空 = 今天行为）。
    title: str | None = None
    angle: Angle | None = None
    # Phase 2b：skill 链多-pass（按 role 顺序）。空 = 退回单 skill_id（零回归）。
    skill_chain: list[str] | None = None
    # Phase 4+：成文契约档单次覆盖（None=用全局设置）。
    contract_mode: Literal["conservative", "aggressive"] | None = None


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
    # angle 是 pydantic 对象——model_dump() 会把它压成 dict，而 GenerateRequest
    # 期望 Angle。显式排除后单独传原对象，其余字段照常透传。
    req = generate_service.GenerateRequest(
        **body.model_dump(exclude={"angle"}),
        angle=body.angle,
    )
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


class ResolveFactcheckBody(BaseModel):
    final_text: str = Field(min_length=1)
    released_numbers: list[float] = Field(default_factory=list)
    released_certs: list[str] = Field(default_factory=list)


@router.post("/api/generate/{job_id}/export")
def resolve_factcheck(job_id: str, body: ResolveFactcheckBody) -> dict:
    """重核一篇被事实核对拦下的成稿（含用户放行项），干净则导出。

    job_id 不是「待事实核对处理」状态（过期 / 从未被拦）→ 404。
    返回 {"ok": True, document/format/title} 或 {"ok": False, violations}。
    """
    try:
        return factcheck_service.resolve_and_export(
            job_id,
            final_text=body.final_text,
            released_numbers=body.released_numbers,
            released_certs=body.released_certs,
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"no pending fact-check for job {job_id}")


class FinalizeBody(BaseModel):
    draft: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    title: str | None = None
    angle: Angle | None = None
    skill_id: str | None = None
    skill_chain: list[str] | None = None
    provider: str | None = None
    model: str | None = None
    # Phase 4+：成文契约档单次覆盖（None=用全局设置）。
    contract_mode: Literal["conservative", "aggressive"] | None = None


@router.post("/api/generate/{job_id}/finalize", response_model=JobAccepted, status_code=202)
def finalize_generate(job_id: str, body: FinalizeBody) -> JobAccepted:
    """在 takeoff 初稿基础上跑「注入+角度+链」成稿。复用 job_id 重开流。
    缓存 plan 已淘汰 / job_id 未知 → 404（前端提示重新起飞）。"""
    if assembler_service.get_plan(job_id) is None:
        raise HTTPException(status_code=404, detail=f"plan cache miss: {job_id}")
    req = generate_service.FinalizeRequest(
        **body.model_dump(exclude={"angle"}), angle=body.angle,
    )
    generate_service.submit_finalize(job_id, req)
    return JobAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")
