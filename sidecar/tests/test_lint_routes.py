import pytest
from fastapi.testclient import TestClient
from csm_core.config import AppConfig, LintConfig
from csm_sidecar.main import app
from csm_sidecar.services import lint_service


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(lint_service.config_service, "load", lambda: AppConfig(lint=LintConfig()))


def test_lint_ok(client):
    r = client.post("/api/lint", json={"text": "业内最佳😀"})
    assert r.status_code == 200
    body = r.json()
    assert "hits" in body and "fixed_text" in body
    assert any(h["category"] == "absolute" for h in body["hits"])


def test_lint_missing_text_422(client):
    assert client.post("/api/lint", json={}).status_code == 422


def test_lint_empty_text_empty_report(client):
    r = client.post("/api/lint", json={"text": ""})
    assert r.status_code == 200
    assert r.json() == {"hits": [], "fixed_text": ""}


def test_lint_requires_auth():
    """无 token → 401/403（与其它路由一致，dependencies=[RequireToken]）。"""
    with TestClient(app) as c:
        resp = c.post("/api/lint", json={"text": "最佳"})
    assert resp.status_code in (401, 403)
