"""Tests for /api/mining/ai_prompts GET / PATCH (Phase 3 T3b)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_get_ai_prompts_initial_empty_current(client: TestClient, monitor_db: Path):
    r = client.get("/api/mining/ai_prompts")
    assert r.status_code == 200
    body = r.json()

    # Shape
    assert set(body.keys()) == {"summary", "suggest", "vars"}
    assert set(body["summary"].keys()) == {"current", "default"}
    assert set(body["suggest"].keys()) == {"current", "default"}

    # Initial current is empty
    assert body["summary"]["current"] == ""
    assert body["suggest"]["current"] == ""

    # Default contains the system+separator+user concatenation
    assert "---user---" in body["summary"]["default"]
    assert "---user---" in body["suggest"]["default"]
    assert body["summary"]["default"]  # non-empty
    assert body["suggest"]["default"]

    # vars list is structured for UI hints
    assert "title" in body["vars"]["summary"]
    assert "tier" in body["vars"]["suggest"]
    assert "previous_block" in body["vars"]["suggest"]


def test_patch_summary_persists(client: TestClient, monitor_db: Path):
    r = client.patch("/api/mining/ai_prompts", json={"summary": "custom sys {title}"})
    assert r.status_code == 200
    assert r.json()["summary"]["current"] == "custom sys {title}"
    # suggest untouched
    assert r.json()["suggest"]["current"] == ""

    # Subsequent GET still shows it
    r2 = client.get("/api/mining/ai_prompts")
    assert r2.json()["summary"]["current"] == "custom sys {title}"


def test_patch_suggest_persists(client: TestClient, monitor_db: Path):
    r = client.patch("/api/mining/ai_prompts", json={"suggest": "x {tier}"})
    assert r.status_code == 200
    assert r.json()["suggest"]["current"] == "x {tier}"
    assert r.json()["summary"]["current"] == ""


def test_patch_both_at_once(client: TestClient, monitor_db: Path):
    r = client.patch(
        "/api/mining/ai_prompts",
        json={"summary": "s", "suggest": "u"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["current"] == "s"
    assert body["suggest"]["current"] == "u"


def test_patch_empty_string_clears(client: TestClient, monitor_db: Path):
    # First set a custom value
    client.patch("/api/mining/ai_prompts", json={"summary": "before"})
    assert client.get("/api/mining/ai_prompts").json()["summary"]["current"] == "before"

    # Now clear back to default
    r = client.patch("/api/mining/ai_prompts", json={"summary": ""})
    assert r.status_code == 200
    assert r.json()["summary"]["current"] == ""


def test_patch_no_fields_returns_400(client: TestClient, monitor_db: Path):
    r = client.patch("/api/mining/ai_prompts", json={})
    assert r.status_code == 400


def test_patch_requires_auth(monitor_db: Path, settings_path: Path):
    """Strip the auth header and confirm 401."""
    from csm_sidecar.main import app
    with TestClient(app) as c:
        r = c.patch("/api/mining/ai_prompts", json={"summary": "x"})
    assert r.status_code == 401
