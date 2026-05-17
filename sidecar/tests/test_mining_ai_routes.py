"""Routes for AI summary + AI suggest (Phase 3 T5).

Reuses the recording-fake LLM client from test_mining_ai_service style.
Confirms:
* happy paths return the expected JSON shapes
* cache hit on second summary call (force=false) skips the LLM
* no provider configured → 503 with code llm_not_configured
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import config_service, mining_ai_service


class _RecordingClient:
    def __init__(self, response: str = "fake summary 60-100 chars 中文"):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(
        mining_ai_service.llm_factory,
        "build_client",
        lambda **kw: client,
    )
    return client


def _insert_video(*, video_id: int = 1) -> int:
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title, author_name) "
        "VALUES(?,?,?,?,?,?)",
        (video_id, "bilibili", f"v-{video_id}", f"https://example/{video_id}",
         "T", "A"),
    )
    return video_id


# ── ai_summary happy + cache ───────────────────────────────────────────
def test_ai_summary_returns_text(
    client: TestClient, monitor_db: Path, settings_path: Path,
    fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()
    r = client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": False})
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == fake_client.response
    assert len(fake_client.calls) == 1


def test_ai_summary_cached_skips_llm(
    client: TestClient, monitor_db: Path, settings_path: Path,
    fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()
    # First call hits the LLM and persists
    client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": False})
    fake_client.calls.clear()
    # Second call should serve the cached value without invoking the LLM
    r2 = client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": False})
    assert r2.status_code == 200
    assert r2.json()["summary"] == fake_client.response
    assert fake_client.calls == []


def test_ai_summary_force_regenerates(
    client: TestClient, monitor_db: Path, settings_path: Path,
    fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()
    client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": False})
    fake_client.response = "freshly regenerated"
    fake_client.calls.clear()
    r = client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": True})
    assert r.status_code == 200
    assert r.json()["summary"] == "freshly regenerated"
    assert len(fake_client.calls) == 1


# ── ai_summary error mapping ───────────────────────────────────────────
def test_ai_summary_no_provider_returns_503(
    client: TestClient, monitor_db: Path, settings_path: Path,
):
    # Don't patch default_provider — load() returns AppConfig with None
    vid = _insert_video()
    r = client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": False})
    assert r.status_code == 503
    body = r.json()
    # FastAPI wraps HTTPException.detail in {"detail": ...}
    assert body["detail"]["code"] == "llm_not_configured"
    assert body["detail"]["detail"]  # non-empty message


def test_ai_summary_missing_video_returns_404(
    client: TestClient, monitor_db: Path, settings_path: Path,
    fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    r = client.post("/api/mining/videos/99999/ai_summary", json={"force": False})
    assert r.status_code == 404


def test_ai_summary_llm_error_returns_502(
    client: TestClient, monitor_db: Path, settings_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Generic exception from the LLM client → 502 llm_error."""
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()

    class _Boom:
        def complete(self, *, system, user, temperature=None):
            raise RuntimeError("upstream 500")

    monkeypatch.setattr(
        mining_ai_service.llm_factory, "build_client", lambda **kw: _Boom(),
    )
    r = client.post(f"/api/mining/videos/{vid}/ai_summary", json={"force": True})
    assert r.status_code == 502
    body = r.json()
    assert body["detail"]["code"] == "llm_error"
    assert "upstream 500" in body["detail"]["detail"]


# ── ai_suggest_comment happy ───────────────────────────────────────────
def test_ai_suggest_comment_returns_text(
    client: TestClient, monitor_db: Path, settings_path: Path,
    fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()
    fake_client.response = "建议草稿 80 字"
    r = client.post(
        f"/api/mining/videos/{vid}/ai_suggest_comment",
        json={"tier": 2, "previous_tiers": ["第一层文本"], "tone_hint": ""},
    )
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"] == "建议草稿 80 字"
    # Renders previous_tiers into the user message
    call = fake_client.calls[0]
    assert "第 1 层: 第一层文本" in call["user"]


def test_ai_suggest_no_provider_returns_503(
    client: TestClient, monitor_db: Path, settings_path: Path,
):
    vid = _insert_video()
    r = client.post(
        f"/api/mining/videos/{vid}/ai_suggest_comment",
        json={"tier": 1, "previous_tiers": []},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "llm_not_configured"
