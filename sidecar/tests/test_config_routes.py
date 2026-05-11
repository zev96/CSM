"""Tests for /api/config and /api/keyring/*."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_config_returns_defaults(client: TestClient):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_provider"] == "mock"
    assert data["concurrency"] == 3
    assert data["monitor"]["enabled"] is False


def test_get_config_requires_auth(settings_path):
    """Strip the auth header and confirm 401."""
    from csm_sidecar.main import app
    with TestClient(app) as c:
        # No Authorization header attached.
        resp = c.get("/api/config")
    assert resp.status_code == 401


def test_patch_config_top_level_field(client: TestClient):
    resp = client.patch("/api/config", json={"vault_root": "C:/some/vault"})
    assert resp.status_code == 200
    assert resp.json()["vault_root"] == "C:/some/vault"

    # Persisted across requests.
    resp2 = client.get("/api/config")
    assert resp2.json()["vault_root"] == "C:/some/vault"


def test_patch_config_deep_merges_nested(client: TestClient):
    # First set two monitor fields.
    client.patch("/api/config", json={"monitor": {"alert_top_n": 7, "concurrency_per_platform": 4}})
    # Then patch only one — the other must survive.
    client.patch("/api/config", json={"monitor": {"alert_top_n": 10}})

    cfg = client.get("/api/config").json()
    assert cfg["monitor"]["alert_top_n"] == 10
    assert cfg["monitor"]["concurrency_per_platform"] == 4


def test_patch_config_invalid_value_returns_422(client: TestClient):
    # default_provider is a Literal — "invalid" should fail validation.
    resp = client.patch("/api/config", json={"default_provider": "not_a_real_provider"})
    assert resp.status_code == 422


def test_keyring_status_default_no_key(client: TestClient, monkeypatch):
    # Force keyring backend to a reliable in-memory fake.
    _install_fake_keyring(monkeypatch)
    resp = client.get("/api/keyring/anthropic")
    assert resp.status_code == 200
    assert resp.json() == {"provider": "anthropic", "has_key": False}


def test_keyring_set_then_status_then_delete(client: TestClient, monkeypatch):
    _install_fake_keyring(monkeypatch)

    set_resp = client.post("/api/keyring/anthropic", json={"value": "sk-ant-test"})
    assert set_resp.status_code == 200
    assert set_resp.json()["has_key"] is True

    status_resp = client.get("/api/keyring/anthropic")
    assert status_resp.json()["has_key"] is True

    del_resp = client.delete("/api/keyring/anthropic")
    assert del_resp.status_code == 200
    assert del_resp.json()["has_key"] is False

    # And confirm it's actually gone.
    assert client.get("/api/keyring/anthropic").json()["has_key"] is False


def test_keyring_set_empty_value_rejected(client: TestClient, monkeypatch):
    _install_fake_keyring(monkeypatch)
    # Pydantic min_length=1 rejects empty.
    resp = client.post("/api/keyring/anthropic", json={"value": ""})
    assert resp.status_code == 422


def test_get_accepts_query_token(settings_path):
    """SSE EventSource can't set custom headers — sidecar must accept
    ``?token=`` on GET routes for that compatibility."""
    from csm_sidecar import auth
    from csm_sidecar.main import app
    with TestClient(app) as c:
        # No Authorization header — pass token via query.
        resp = c.get(f"/api/config?token={auth.get_token()}")
    assert resp.status_code == 200


def test_post_rejects_query_token(settings_path):
    """Query token is GET-only — POST/PATCH/DELETE must use the header."""
    from csm_sidecar import auth
    from csm_sidecar.main import app
    with TestClient(app) as c:
        resp = c.patch(
            f"/api/config?token={auth.get_token()}",
            json={"vault_root": "/x"},
        )
    assert resp.status_code == 401


def test_invalid_query_token_rejected(settings_path):
    from csm_sidecar.main import app
    with TestClient(app) as c:
        resp = c.get("/api/config?token=not-the-real-token")
    assert resp.status_code == 401


def test_keyring_unavailable_backend_returns_503(client: TestClient, monkeypatch):
    """If the keyring package can't write, the route surfaces 503."""
    # routes/config.py imports set_secret by name, so the route binding is
    # what we have to swap — patching csm_core.config.set_secret alone
    # leaves the route holding a stale reference.
    monkeypatch.setattr("csm_sidecar.routes.config.set_secret", lambda p, v: False)
    resp = client.post("/api/keyring/openai", json={"value": "sk-x"})
    assert resp.status_code == 503


# ── Helpers ────────────────────────────────────────────────────────────────
def _install_fake_keyring(monkeypatch):
    """Replace csm_core.config's keyring helpers with an in-process dict.

    Using monkeypatch on the module-level functions is simpler than swapping
    the keyring backend, and tests run identically on a CI box that has no
    secret service installed.
    """
    store: dict[str, str] = {}

    def fake_get(provider: str) -> str | None:
        return store.get(provider)

    def fake_set(provider: str, value: str) -> bool:
        store[provider] = value
        return True

    def fake_delete(provider: str) -> bool:
        return store.pop(provider, None) is not None

    monkeypatch.setattr("csm_core.config.get_secret", fake_get)
    monkeypatch.setattr("csm_core.config.set_secret", fake_set)
    monkeypatch.setattr("csm_core.config.delete_secret", fake_delete)
    # routes/config.py imports the names directly — patch those too.
    monkeypatch.setattr("csm_sidecar.routes.config.get_secret", fake_get)
    monkeypatch.setattr("csm_sidecar.routes.config.set_secret", fake_set)
    monkeypatch.setattr("csm_sidecar.routes.config.delete_secret", fake_delete)
