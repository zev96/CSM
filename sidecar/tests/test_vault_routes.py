"""Tests for /api/vault/scan and /api/vault/notes."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _write_note(p: Path, *, frontmatter: dict | None = None, body: str = "") -> None:
    """Write a vault note. ``scan_vault`` drops notes with empty frontmatter,
    so tests that expect a note to appear in the index must pass non-empty
    frontmatter."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = frontmatter or {"module": "default"}  # ensure non-empty for scan_vault
    parts = ["---"]
    for k, v in fm.items():
        parts.append(f"{k}: {v}")
    parts.append("---")
    parts.append(body)
    p.write_text("\n".join(parts), encoding="utf-8")


def test_scan_404_when_root_missing(client: TestClient, tmp_path):
    resp = client.post("/api/vault/scan", json={"root": str(tmp_path / "does-not-exist")})
    assert resp.status_code == 404


def test_scan_400_when_no_root_anywhere(client: TestClient):
    # vault_root unset in config and no override → 400
    resp = client.post("/api/vault/scan", json={})
    assert resp.status_code == 400


def test_scan_returns_summary(client: TestClient, tmp_path):
    vault = tmp_path / "vault"
    _write_note(vault / "营销资料库" / "标题模块" / "test.md",
                frontmatter={"module": "标题"}, body="① first\n② second")
    _write_note(vault / "其他" / "blank.md", body="just text, no variants")

    resp = client.post("/api/vault/scan", json={"root": str(vault)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["root"] == str(vault)
    assert data["note_count"] == 2


def test_list_notes_409_without_prior_scan(client: TestClient):
    resp = client.get("/api/vault/notes")
    assert resp.status_code == 409


def test_list_notes_after_scan(client: TestClient, tmp_path):
    vault = tmp_path / "vault"
    _write_note(vault / "营销资料库" / "标题模块" / "a.md", frontmatter={"x": 1}, body="① one")
    _write_note(vault / "营销资料库" / "标题模块" / "b.md", body="② two\n③ three")
    _write_note(vault / "其他" / "c.md", body="no variants")

    client.post("/api/vault/scan", json={"root": str(vault)})

    all_resp = client.get("/api/vault/notes")
    assert all_resp.status_code == 200
    assert all_resp.json()["count"] == 3

    filtered = client.get("/api/vault/notes", params={"module": "营销资料库/标题模块"})
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["count"] == 2
    assert {n["id"] for n in body["notes"]} == {"a", "b"}


def test_scan_uses_config_vault_root_when_no_override(client: TestClient, tmp_path):
    vault = tmp_path / "configured-vault"
    _write_note(vault / "x.md", body="hi")
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/scan", json={})
    assert resp.status_code == 200
    assert resp.json()["note_count"] == 1
