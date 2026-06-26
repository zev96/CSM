"""skill 链逐 pass 重跑端点。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from csm_core.llm import pricing

from ..auth import RequireToken
from ..services import chain_service, config_service

router = APIRouter(tags=["chain"], dependencies=[RequireToken])


class ChainRerunBody(BaseModel):
    job_id: str = Field(min_length=1)
    pass_index: int = Field(ge=0)


@router.post("/api/chain/rerun")
def chain_rerun(body: ChainRerunBody) -> dict[str, Any]:
    """重跑 pass_index 并级联其后；返回更新后的 passes + final_text + cost。

    404 未知 job（缓存淘汰 / 旧 job）；400 pass_index 越界。
    cost 单独算：实际 model = 链缓存里的 model 否则该 provider 默认 model。"""
    try:
        res = chain_service.rerun(body.job_id, body.pass_index)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    cfg = config_service.load()
    # state 理论上必在（rerun 刚成功并回写缓存）；极端 LRU 淘汰竞态下为 None
    # → model=None → cost=None 降级（只显 token，不显 ¥），不崩。
    state = chain_service.get_state(body.job_id)
    model = None
    if state is not None:
        model = state.model or cfg.default_model.get(state.provider or cfg.default_provider or "")
    res["cost"] = pricing.chain_cost(res["passes"], model, cfg.pricing)
    return res
