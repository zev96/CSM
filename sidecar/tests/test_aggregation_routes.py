"""Tests for /api/recent."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


def _write_doc(p: Path, *, content: str = "", mtime: datetime | None = None,
               with_frontmatter: bool = True, title: str = "测试标题",
               template: str | None = "导购文-基础") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if with_frontmatter:
        fm_lines = ["---", f"title: {title}"]
        if template:
            fm_lines.append(f"template: {template}")
        fm_lines.append("---")
        body = "\n".join(fm_lines) + "\n" + content
    else:
        body = content
    p.write_text(body, encoding="utf-8")
    if mtime is not None:
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))


# ── /api/recent ─────────────────────────────────────────────────────────────
def test_recent_empty_when_history_unset(client: TestClient):
    resp = client.get("/api/recent")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "documents": []}


def test_recent_lists_files_newest_first(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})

    now = datetime.now()
    _write_doc(history / "old.md", content="x" * 50, mtime=now - timedelta(days=2),
               title="old article")
    _write_doc(history / "new.md", content="y" * 50, mtime=now - timedelta(hours=1),
               title="new article")

    data = client.get("/api/recent").json()
    assert data["count"] == 2
    # Newest first.
    assert data["documents"][0]["title"] == "new article"
    assert data["documents"][1]["title"] == "old article"
    assert data["documents"][0]["template_name"] == "导购文-基础"


def test_recent_drops_files_outside_window(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    now = datetime.now()
    _write_doc(history / "fresh.md", mtime=now - timedelta(days=2))
    _write_doc(history / "stale.md", mtime=now - timedelta(days=30))

    data = client.get("/api/recent", params={"days": 7}).json()
    assert data["count"] == 1
    assert data["documents"][0]["filename"] == "fresh.md"


def test_recent_limit_respected(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    now = datetime.now()
    for i in range(8):
        _write_doc(history / f"d{i}.md", mtime=now - timedelta(hours=i))
    data = client.get("/api/recent", params={"limit": 3}).json()
    assert data["count"] == 3


def test_recent_only_lists_markdown(client: TestClient, tmp_path: Path):
    """History dir holds .md mirrors only — any stray .docx must be ignored."""
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    _write_doc(history / "yes.md", title="md only")
    (history / "no.docx").write_bytes(b"not really a docx")
    data = client.get("/api/recent").json()
    assert data["count"] == 1
    assert data["documents"][0]["filename"] == "yes.md"
