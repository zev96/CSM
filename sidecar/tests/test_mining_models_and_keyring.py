"""Final fix round — new coverage that didn't have a natural home elsewhere:

- C1: ``StartJobRequest.platforms`` dedupe + bound (unbounded duplicates
  are a paid-search amplifier once the runner dispatches to TikHub).
- I7: ``/api/keyring/{provider}`` GET must resolve ``has_key`` the same way
  ``csm_core.config.read_api_key`` resolves the key the backend actually
  uses (OS keyring first, ``AppConfig.api_keys`` plaintext fallback).
- S1-route: ``/api/keyring/{provider}`` POST must reject keys containing
  non-ASCII / control characters (full-width paste, invisible characters)
  at save time instead of silently persisting a key that will never work.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from csm_core.mining.models import StartJobRequest
from csm_sidecar.services import config_service


# ── C1 ───────────────────────────────────────────────────────────────────

def test_platforms_dedupe_massive_duplicates():
    """500x the same platform must collapse to one entry, not fan out into
    500 TikHub search requests for a single job."""
    req = StartJobRequest(keyword="k", platforms=["douyin"] * 500)
    assert req.platforms == ["douyin"]


def test_platforms_dedupe_preserves_order():
    req = StartJobRequest(
        keyword="k", platforms=["douyin", "bilibili", "douyin", "kuaishou"],
    )
    assert req.platforms == ["douyin", "bilibili", "kuaishou"]


def test_platforms_empty_list_rejected():
    with pytest.raises(ValidationError):
        StartJobRequest(keyword="k", platforms=[])


def test_platforms_invalid_platform_rejected():
    with pytest.raises(ValidationError):
        StartJobRequest(keyword="k", platforms=["xhs"])


# ── I7 ───────────────────────────────────────────────────────────────────

def test_keyring_status_true_via_plaintext_fallback(client: TestClient, monkeypatch):
    """OS keyring backend returns nothing, but the key still sits in
    AppConfig.api_keys (transition-window fallback, e.g. Linux box without
    a working secret-service backend) — status must report has_key=True,
    the same thing read_api_key() would hand the real TikHub client."""
    monkeypatch.setattr("csm_core.config.get_secret", lambda provider: None)
    config_service.patch({"api_keys": {"tikhub": "k"}})

    resp = client.get("/api/keyring/tikhub")
    assert resp.status_code == 200
    assert resp.json() == {"provider": "tikhub", "has_key": True}


def test_keyring_status_false_when_neither_source_has_it(client: TestClient, monkeypatch):
    monkeypatch.setattr("csm_core.config.get_secret", lambda provider: None)
    resp = client.get("/api/keyring/tikhub")
    assert resp.status_code == 200
    assert resp.json() == {"provider": "tikhub", "has_key": False}


def test_keyring_status_true_via_os_keyring(client: TestClient, monkeypatch):
    """Sanity check the other branch: OS keyring has it, api_keys is empty."""
    monkeypatch.setattr("csm_core.config.get_secret", lambda provider: "from-keyring")
    resp = client.get("/api/keyring/tikhub")
    assert resp.status_code == 200
    assert resp.json() == {"provider": "tikhub", "has_key": True}


# ── S1-route ─────────────────────────────────────────────────────────────

def test_keyring_set_rejects_non_ascii(client: TestClient, monkeypatch):
    # Mirror the existing keyring-route tests' pattern (see
    # test_config_routes.py::test_keyring_unavailable_backend_returns_503):
    # the route imports set_secret by name, so mock the route's binding.
    monkeypatch.setattr("csm_sidecar.routes.config.set_secret", lambda p, v: True)
    # Zero-width space (U+200B) riding along with an otherwise-normal key —
    # the classic "looks fine, fails every request" paste artifact.
    tainted = "sk" + chr(0x200B) + "key"
    resp = client.post("/api/keyring/tikhub", json={"value": tainted})
    assert resp.status_code == 400
    assert "非 ASCII" in resp.json()["detail"]


def test_keyring_set_rejects_control_characters(client: TestClient, monkeypatch):
    monkeypatch.setattr("csm_sidecar.routes.config.set_secret", lambda p, v: True)
    resp = client.post("/api/keyring/tikhub", json={"value": "sk-ok\nsk-more"})
    assert resp.status_code == 400
    assert "非 ASCII" in resp.json()["detail"]


def test_keyring_set_accepts_clean_ascii(client: TestClient, monkeypatch):
    monkeypatch.setattr("csm_sidecar.routes.config.set_secret", lambda p, v: True)
    resp = client.post("/api/keyring/tikhub", json={"value": "sk-ok"})
    assert resp.status_code == 200
    assert resp.json()["has_key"] is True
