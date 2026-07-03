import pytest

from csm_core.config import AppConfig, ScoringConfig
from csm_sidecar.services import score_service


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(
        score_service.config_service, "load", lambda: AppConfig())


def test_score_ok(client):
    r = client.post("/api/score", json={"text": "上周换了台吸尘器，好用。"})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["total"] <= 100 and isinstance(body["parts"], list)


def test_score_with_signals(client):
    r = client.post("/api/score", json={
        "text": "首先好。其次妙。最后强。", "factcheck_violations": 1,
        "completeness_missing": 2})
    body = r.json()
    keys = {p["key"] for p in body["parts"]}
    assert {"factcheck", "completeness"} <= keys


def test_score_disabled(client, monkeypatch):
    monkeypatch.setattr(
        score_service.config_service, "load",
        lambda: AppConfig(scoring=ScoringConfig(enabled=False)))
    r = client.post("/api/score", json={"text": "x"})
    assert r.status_code == 200
    assert r.json() == {"total": None, "parts": []}


def test_score_missing_text_422(client):
    assert client.post("/api/score", json={}).status_code == 422
