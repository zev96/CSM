"""Routes for xhs AI 生成/润色（P3）.

错误映射沿用 mining：无 provider → 503 llm_not_configured；LLM 抛异常 → 502
llm_error；空入参 → 400。Happy path 用 recording fake 注入。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_sidecar.services import config_service, xhs_ai_service


class _RecordingClient:
    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(
        xhs_ai_service.llm_factory, "build_client", lambda **kw: client,
    )
    return client


# ── generate ──────────────────────────────────────────────────────────────
def test_generate_returns_title_body_topics(
    client: TestClient, settings_path: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = '{"title": "T", "body": "B", "topics": ["x", "y"]}'
    r = client.post("/api/xhs/ai/generate", json={"intent": "平价护肤"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"title": "T", "body": "B", "topics": ["x", "y"]}


def test_generate_empty_intent_returns_400(client: TestClient, settings_path: Path):
    # 400 在调 service 之前就触发，无需配置 LLM。
    r = client.post("/api/xhs/ai/generate", json={"intent": "   "})
    assert r.status_code == 400


def test_generate_no_provider_returns_503(client: TestClient, settings_path: Path):
    r = client.post("/api/xhs/ai/generate", json={"intent": "主题"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "llm_not_configured"


def test_generate_llm_error_returns_502(
    client: TestClient, settings_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    config_service.patch({"default_provider": "mock"})

    class _Boom:
        def complete(self, *, system, user, temperature=None):
            raise RuntimeError("upstream 500")

    monkeypatch.setattr(
        xhs_ai_service.llm_factory, "build_client", lambda **kw: _Boom(),
    )
    r = client.post("/api/xhs/ai/generate", json={"intent": "主题"})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "llm_error"
    assert "upstream 500" in r.json()["detail"]["detail"]


# ── polish ────────────────────────────────────────────────────────────────
def test_polish_returns_body(
    client: TestClient, settings_path: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = "润色后正文"
    r = client.post("/api/xhs/ai/polish", json={"text": "朴素正文"})
    assert r.status_code == 200, r.text
    assert r.json() == {"body": "润色后正文"}


def test_polish_empty_text_returns_400(client: TestClient, settings_path: Path):
    # 400 在调 service 之前就触发，无需配置 LLM。
    r = client.post("/api/xhs/ai/polish", json={"text": ""})
    assert r.status_code == 400


def test_polish_no_provider_returns_503(client: TestClient, settings_path: Path):
    r = client.post("/api/xhs/ai/polish", json={"text": "正文"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "llm_not_configured"
