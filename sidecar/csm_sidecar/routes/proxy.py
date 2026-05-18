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
        from csm_core.browser_infra import patchright_pool
        pool = patchright_pool.get_current_proxy_pool()
        if pool is None:
            # No pool created yet (sidecar hasn't acquired a browser since last config change).
            # Construct a transient instance to read enabled/count from config —
            # disabled_count=0 since no runtime state to surface yet.
            pool = ProxyPool(Path(proxies_path))
        return {
            "enabled": pool.enabled,
            "available_count": len(pool.available_proxies()),
            "disabled_count": pool.disabled_count(),
        }
    except Exception:
        return {"enabled": False, "available_count": 0, "disabled_count": 0}
