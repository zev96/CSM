"""Per-pick reroll endpoint."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from csm_core.assembler.reroll import NoCandidatesError

from ..auth import RequireToken
from ..services import assembler_service

router = APIRouter(tags=["assembler"], dependencies=[RequireToken])


class RerollBody(BaseModel):
    job_id: str = Field(min_length=1, description="job_id from /api/generate")
    block_id: str = Field(min_length=1)
    pick_index: int = Field(ge=0)


@router.post("/api/assembler/reroll")
async def reroll(body: RerollBody) -> dict[str, Any]:
    """Replace one pick in the cached plan and return the updated plan + draft.

    Errors:
    - 404 — unknown job_id (plan was evicted from the LRU cache, e.g.
      after >50 newer jobs); template missing on disk
    - 409 — no candidates left (the source pool is exhausted for this slot)
    - 400 — config incomplete (vault_root unset)
    """
    try:
        return assembler_service.reroll(
            body.job_id, body.block_id, body.pick_index,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except NoCandidatesError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
