"""Tests for /api/title, /api/polish/block, /api/export/{fmt}.

LLM calls are mocked via the ``mock`` provider so tests are fast and
deterministic.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


# ── /api/title ──────────────────────────────────────────────────────────────
def test_title_with_no_vault_root_returns_400(client: TestClient):
    resp = client.post("/api/title", json={"keyword": "无线吸尘器"})
    assert resp.status_code == 400
    assert "vault_root" in resp.json()["detail"]


def test_title_with_mock_provider_falls_back(client: TestClient, tmp_path: Path):
    """Title pipeline always returns ≥1 candidate; mock LLM forces fallback."""
    vault = tmp_path / "vault"
    vault.mkdir()
    client.patch("/api/config", json={
        "vault_root": str(vault),
        "default_provider": "mock",
    })
    resp = client.post("/api/title", json={"keyword": "无线吸尘器"})
    assert resp.status_code == 200
    cands = resp.json()["candidates"]
    assert isinstance(cands, list) and len(cands) >= 1
    # Fallback always preserves the keyword verbatim.
    assert all("无线吸尘器" in c for c in cands)


# ── /api/polish/block ───────────────────────────────────────────────────────
def test_polish_block_uses_llm_and_returns_text(client: TestClient):
    client.patch("/api/config", json={"default_provider": "mock"})
    resp = client.post("/api/polish/block", json={"text": "原段落内容"})
    assert resp.status_code == 200
    # MockClient returns "mock response" by default.
    assert resp.json()["text"] == "mock response"


def test_polish_block_empty_input_422(client: TestClient):
    client.patch("/api/config", json={"default_provider": "mock"})
    resp = client.post("/api/polish/block", json={"text": ""})
    assert resp.status_code == 422


def test_polish_block_missing_api_key_400(client: TestClient):
    """Non-mock provider with no key → 400 from LLMConfigError."""
    client.patch("/api/config", json={"default_provider": "anthropic"})
    resp = client.post("/api/polish/block", json={"text": "hi"})
    assert resp.status_code == 400
    assert "api key" in resp.json()["detail"].lower()


# ── /api/export/{fmt} ───────────────────────────────────────────────────────
def test_export_markdown_writes_file(client: TestClient, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    client.patch("/api/config", json={"out_dir": str(out)})
    resp = client.post("/api/export/markdown", json={
        "keyword": "kw",
        "final_text": "# Title\n\nbody",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "markdown"
    assert data["title"] == "Title"
    assert Path(data["document"]).exists()
    assert Path(data["document"]).suffix == ".md"


def test_export_unknown_format_400(client: TestClient, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    client.patch("/api/config", json={"out_dir": str(out)})
    resp = client.post("/api/export/weixin", json={
        "keyword": "kw",
        "final_text": "body",
    })
    assert resp.status_code == 400


def test_export_with_explicit_out_dir_overrides_config(client: TestClient, tmp_path: Path):
    cfg_dir = tmp_path / "cfg-out"
    explicit = tmp_path / "explicit-out"
    explicit.mkdir()
    client.patch("/api/config", json={"out_dir": str(cfg_dir)})
    resp = client.post("/api/export/markdown", json={
        "keyword": "kw",
        "final_text": "body",
        "out_dir": str(explicit),
    })
    assert resp.status_code == 200
    assert Path(resp.json()["document"]).parent == explicit


def test_export_no_out_dir_anywhere_400(client: TestClient):
    resp = client.post("/api/export/markdown", json={
        "keyword": "kw",
        "final_text": "body",
    })
    assert resp.status_code == 400
