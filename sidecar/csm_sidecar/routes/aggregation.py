"""Home-screen aggregation routes: recent documents."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..auth import RequireToken
from ..services import aggregation_service

router = APIRouter(tags=["aggregation"], dependencies=[RequireToken])


@router.get("/api/recent")
def list_recent(
    limit: int = Query(default=5, ge=1, le=50),
    days: int = Query(default=7, ge=1, le=365),
) -> dict[str, Any]:
    """Recent exported documents under the history dir — feeds home 最近文档."""
    return aggregation_service.list_recent(limit=limit, days=days)
