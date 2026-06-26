"""skill 链逐 pass 重跑端点（异步流式：202 + SSE，仿 generate/finalize）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import chain_service, generate_service

router = APIRouter(tags=["chain"], dependencies=[RequireToken])


class ChainRerunBody(BaseModel):
    job_id: str = Field(min_length=1)
    pass_index: int = Field(ge=0)


@router.post("/api/chain/rerun", status_code=202)
def chain_rerun(body: ChainRerunBody) -> dict[str, Any]:
    """从 pass_index 起级联重跑，异步流式。返回 {job_id, stream_url}，逐 pass 经
    SSE `pass` 推、`done` 带 passes+final_text+cost。

    404 未知 job（缓存淘汰 / 旧 job）；400 pass_index 越界 —— 均同步前置校验
    （worker 异步无法回 HTTP 码）。"""
    state = chain_service.get_state(body.job_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"chain cache miss: {body.job_id}")
    if not (0 <= body.pass_index < len(state.passes)):
        raise HTTPException(
            status_code=400,
            detail=f"pass_index {body.pass_index} out of range (0..{len(state.passes)-1})")
    generate_service.submit_rerun(body.job_id, body.pass_index)
    return {"job_id": body.job_id, "stream_url": f"/api/events/{body.job_id}"}
