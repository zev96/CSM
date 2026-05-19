"""Config + keyring HTTP routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from csm_core.config import AppConfig, delete_secret, get_secret, set_secret

from ..auth import RequireToken
from ..services import config_service

router = APIRouter(tags=["config"], dependencies=[RequireToken])


@router.get("/api/config", response_model=AppConfig)
async def get_config() -> AppConfig:
    """Return the current AppConfig.

    NB: ``api_keys`` field is included for backward compat but should not
    be relied on — keys are migrating to the OS keyring (see ``/api/keyring``).
    """
    return config_service.load()


@router.patch("/api/config", response_model=AppConfig)
async def patch_config(updates: dict[str, Any]) -> AppConfig:
    """Apply a partial update. Nested dicts (e.g. monitor) are deep-merged.

    Body shape: any subset of AppConfig's JSON form. Examples::

        {"vault_root": "/path/to/vault"}
        {"monitor": {"alert_top_n": 7}}
        {"default_provider": "anthropic", "default_model": {"anthropic": "claude-opus-4-7"}}

    When ``monitor.*`` fields change, the live adapters are reconfigured
    so users don't need to restart sidecar after editing default exclude
    domains / pacing / breaker thresholds. reconfigure() is idempotent
    and swallows internal exceptions, so PATCH still returns 200 even if
    an adapter rejected the new value.
    """
    try:
        new_cfg = config_service.patch(updates)
    except ValueError as e:  # pydantic ValidationError subclasses ValueError
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # Hot-reload adapter settings only when monitor.* actually changed.
    # Lazy import: routes are imported during app boot before
    # monitor_lifecycle is fully ready; module-level import would create
    # a circular dep with config_service.
    if "monitor" in updates:
        from ..services import monitor_lifecycle
        monitor_lifecycle.reconfigure(new_cfg)

    return new_cfg


# ── Keyring sub-routes ──────────────────────────────────────────────────────
class KeyringStatus(BaseModel):
    provider: str
    has_key: bool


class KeyringSet(BaseModel):
    value: str = Field(min_length=1, description="API key plaintext")


@router.get("/api/keyring/{provider}", response_model=KeyringStatus)
async def keyring_status(provider: str) -> KeyringStatus:
    """Report whether a key is set for ``provider``. Never returns the value."""
    return KeyringStatus(provider=provider, has_key=get_secret(provider) is not None)


@router.post("/api/keyring/{provider}", response_model=KeyringStatus)
async def keyring_set(provider: str, body: KeyringSet) -> KeyringStatus:
    """Persist an API key for ``provider`` in the OS credential store."""
    ok = set_secret(provider, body.value)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="keyring backend unavailable",
        )
    return KeyringStatus(provider=provider, has_key=True)


@router.delete("/api/keyring/{provider}", response_model=KeyringStatus)
async def keyring_delete(provider: str) -> KeyringStatus:
    """Remove the stored key. Idempotent — already-absent is success."""
    delete_secret(provider)
    return KeyringStatus(provider=provider, has_key=False)
