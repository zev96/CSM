"""只读：角度受控词表（前端 picker 数据源，单一来源在后端）。"""
from __future__ import annotations

from fastapi import APIRouter

from csm_core.angle import taxonomy as t

from ..auth import RequireToken

router = APIRouter(tags=["angle"], dependencies=[RequireToken])


@router.get("/api/angle/taxonomy")
def get_taxonomy() -> dict:
    return {
        "tones": [{"key": k, "hint": v} for k, v in t.TONES.items()],
        "dimensions": t.SELLPOINT_DIMENSIONS,
        "audiences": list(t.AUDIENCES.keys()),
        "presets": [
            {"name": p["name"], "template_id": p["template_id"],
             "audience": p["audience"], "sellpoints": p["sellpoints"], "tone": p["tone"]}
            for p in t.PRESETS
        ],
    }
