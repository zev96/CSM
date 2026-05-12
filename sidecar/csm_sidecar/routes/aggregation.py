"""Home-screen aggregation routes: recent / calendar / stats."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..auth import RequireToken
from ..services import aggregation_service

router = APIRouter(tags=["aggregation"], dependencies=[RequireToken])


@router.get("/api/recent")
async def list_recent(
    limit: int = Query(default=5, ge=1, le=50),
    days: int = Query(default=7, ge=1, le=365),
) -> dict[str, Any]:
    """Recent exported documents under ``out_dir`` — feeds home 最近文档."""
    return aggregation_service.list_recent(limit=limit, days=days)


@router.get("/api/calendar")
async def calendar_view(
    month: str | None = Query(
        default=None, description="YYYY-MM format; defaults to current month",
    ),
) -> dict[str, Any]:
    """Per-day completed count for ``month``.

    ``scheduled`` is returned as all-zeros — see aggregation_service docstring.
    """
    if month:
        try:
            year, m = map(int, month.split("-", 1))
            if not (1 <= m <= 12):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"invalid month format: {month!r} (use YYYY-MM)",
            )
    else:
        today = date.today()
        year, m = today.year, today.month
    return aggregation_service.calendar_for_month(year, m)


@router.get("/api/stats/words")
async def stats_words(
    range: str = Query(default="this-week"),
) -> dict[str, Any]:
    """Word counts for ``yesterday`` or ``this-week``."""
    try:
        return aggregation_service.words_for_range(range)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
