"""Config + keyring HTTP routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from csm_core.config import AppConfig, delete_secret, get_secret, read_api_key, set_secret

from ..auth import RequireToken
from ..services import config_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"], dependencies=[RequireToken])


@router.get("/api/config", response_model=AppConfig)
def get_config() -> AppConfig:
    """Return the current AppConfig.

    NB: ``api_keys`` field is included for backward compat but should not
    be relied on — keys are migrating to the OS keyring (see ``/api/keyring``).
    """
    return config_service.load()


@router.patch("/api/config", response_model=AppConfig)
def patch_config(updates: dict[str, Any]) -> AppConfig:
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
    # a circular dep with config_service. Wrap in try/except so an
    # adapter that rejects the new value doesn't bubble up to a 500
    # response — the docstring promises "still returns 200" and tests
    # rely on that contract. _apply_runtime_settings already swallows
    # adapter-level failures internally; this catches anything ELSE
    # (e.g. a future refactor that adds a top-level check).
    if "monitor" in updates:
        from ..services import monitor_lifecycle
        try:
            monitor_lifecycle.reconfigure(new_cfg)
        except Exception:
            logger.exception("monitor_lifecycle.reconfigure raised; PATCH still returns 200")

    return new_cfg


# ── Keyring sub-routes ──────────────────────────────────────────────────────
class KeyringStatus(BaseModel):
    provider: str
    has_key: bool


class KeyringSet(BaseModel):
    value: str = Field(min_length=1, description="API key plaintext")


@router.get("/api/keyring/{provider}", response_model=KeyringStatus)
def keyring_status(provider: str) -> KeyringStatus:
    """Report whether a key is set for ``provider``. Never returns the value.

    I7: must use the SAME resolution the backend consumer (``read_api_key``)
    uses — ``get_secret(provider) is not None`` alone misses users whose OS
    keyring backend is unavailable (or absent, e.g. a Linux box without a
    working secret-service) and who therefore still have their key sitting
    in the ``AppConfig.api_keys`` plaintext fallback: they'd see "no key"
    here while the actual API calls succeed, or vice versa.
    """
    cfg = config_service.load()
    has_key = bool((read_api_key(provider, cfg) or "").strip())
    return KeyringStatus(provider=provider, has_key=has_key)


@router.post("/api/keyring/{provider}", response_model=KeyringStatus)
def keyring_set(provider: str, body: KeyringSet) -> KeyringStatus:
    """Persist an API key for ``provider`` in the OS credential store."""
    value = body.value
    # S1: reject non-ASCII / control characters up front. These almost
    # always come from a full-width paste or an invisible character
    # (zero-width space, curly quotes, a copied-in newline) riding along
    # with the key — the resulting string LOOKS right in the UI but fails
    # every downstream API call with an opaque auth error. Catch it here,
    # at save time, with an actionable message instead.
    if not value.isascii() or any(ord(c) < 32 for c in value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key 含非 ASCII 或控制字符（常见于全角字符 / 不可见空格），请检查后重新粘贴",
        )
    ok = set_secret(provider, value)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="keyring backend unavailable",
        )
    return KeyringStatus(provider=provider, has_key=True)


@router.delete("/api/keyring/{provider}", response_model=KeyringStatus)
def keyring_delete(provider: str) -> KeyringStatus:
    """Remove the stored key. Idempotent — already-absent is success."""
    delete_secret(provider)
    return KeyringStatus(provider=provider, has_key=False)
