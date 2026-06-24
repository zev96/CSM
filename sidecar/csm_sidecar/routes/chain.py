"""skill 链逐 pass 重跑端点。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import chain_service

router = APIRouter(tags=["chain"], dependencies=[RequireToken])


class ChainRerunBody(BaseModel):
    job_id: str = Field(min_length=1)
    pass_index: int = Field(ge=0)


@router.post("/api/chain/rerun")
def chain_rerun(body: ChainRerunBody) -> dict[str, Any]:
    """重跑 pass_index 并级联其后；返回更新后的 passes + final_text。

    404 未知 job（缓存淘汰 / 旧 job）；400 pass_index 越界。"""
    try:
        return chain_service.rerun(body.job_id, body.pass_index)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
