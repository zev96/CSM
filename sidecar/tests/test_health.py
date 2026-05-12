"""Smoke test: app boots, /health returns ok, /api/version requires no auth."""
from __future__ import annotations

from fastapi.testclient import TestClient

from csm_sidecar.main import app


def test_health_no_auth_required() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_version_no_auth_required() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/version")
    assert resp.status_code == 200
    assert "sidecar" in resp.json()


def test_shutdown_requires_token() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/shutdown")
    assert resp.status_code == 401


def test_lifespan_preserves_pre_minted_token() -> None:
    """Regression: main.run() prints the token to stdout *before* uvicorn
    starts the lifespan. If lifespan re-mints, Tauri's captured token is
    instantly invalidated and every authed request returns 401.
    """
    from csm_sidecar import auth

    # Simulate main.run()'s pre-mint
    pre = auth.generate_token()
    try:
        # Booting the app (which runs the lifespan) must NOT replace it.
        with TestClient(app):
            assert auth.get_token() == pre
    finally:
        # Reset module state so other tests aren't affected.
        auth._TOKEN = None  # type: ignore[attr-defined]
