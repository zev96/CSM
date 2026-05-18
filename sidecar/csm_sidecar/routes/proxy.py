"""Proxy pool status endpoint for Settings UI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response

from ..auth import RequireToken

router = APIRouter(tags=["proxy"], dependencies=[RequireToken])


@router.get("/api/proxy/status")
async def proxy_status(response: Response) -> dict[str, Any]:
    """Frontend Settings shows: enabled + usable / disabled counts.
    Defensive: returns {enabled: False, ...} if config missing or parse fails."""
    response.headers["Cache-Control"] = "no-store"
    from csm_sidecar.services import config_service
    from csm_core.browser_infra.proxy_pool import ProxyPool

    try:
        cfg = config_service.load()
        proxies_path = getattr(cfg, "proxies_path", None)
    except Exception:
        return {"enabled": False, "available_count": 0, "disabled_count": 0}

    if not proxies_path:
        return {"enabled": False, "available_count": 0, "disabled_count": 0}

    try:
        pool = ProxyPool(Path(proxies_path))
        return {
            "enabled": pool.enabled,
            "available_count": len(pool.available_proxies()),
            "disabled_count": len(getattr(pool, "_disabled", set())),
        }
    except Exception:
        return {"enabled": False, "available_count": 0, "disabled_count": 0}
