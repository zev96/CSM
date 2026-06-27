"""AI 拆条路由（与确定性 vault_writer 分文件——单一职责，它会因 LLM 配置 503）。

关键顺序：LLMConfigError 必须先于 ValueError 捕获（它 subclass ValueError），
否则未配 provider 会被误判成 400 而不是 503。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import RequireToken
from ..services import atomize_service
from ..services.llm_factory import LLMConfigError

router = APIRouter(tags=["vault_atomize"], dependencies=[RequireToken])


class AtomizeBody(BaseModel):
    text: str            # 缺字段 → 422；空串 → service 返回 []（不打 LLM）


@router.post("/api/vault/atomize")
def atomize(body: AtomizeBody) -> dict:
    try:
        return {"atoms": atomize_service.atomize(body.text)}
    except LLMConfigError as e:        # 必须先于 ValueError（subclass）
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except ValueError as e:            # vault_root 未配/不存在
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OSError as e:               # 共享盘断开/占用（scan 阶段）
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"拆条失败：素材库不可读（共享盘断开或文件被占用）: {e}")
