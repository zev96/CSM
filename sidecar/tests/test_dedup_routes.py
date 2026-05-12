"""Tests for /api/dedup/* and /api/keyword/density.

Approach: drive the service directly via HTTP for build-index submission,
then poll the in-memory analyzer for completion rather than consuming
SSE. The SSE wire format is already covered by test_event_bus.py and
test_generate_routes.py — re-validating it here would be redundant and
the iter_lines+EventSourceResponse interaction is finicky against
TestClient.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_sidecar.event_bus import bus as event_bus
from csm_sidecar.services import dedup_service


@pytest.fixture(autouse=True)
def reset_dedup_singleton(monkeypatch: pytest.MonkeyPatch):
    """The DedupAnalyzer is a process singleton — wipe it before each test
    so a previous test's index doesn't leak. Also reset the loaded-kinds
    tracking set."""
    monkeypatch.setattr(dedup_service, "_analyzer", None, raising=True)
    monkeypatch.setattr(dedup_service, "_loaded_kinds", set(), raising=True)
    yield


def _seed_corpus(d: Path, *docs: tuple[str, str]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for name, body in docs:
        (d / name).write_text(body, encoding="utf-8")


def _wait_for_job_done(job_id: str, timeout: float = 10.0) -> dict | None:
    """Poll the EventBus internal buffer for the terminal event without
    opening an SSE stream. Returns the done/error event dict or None on
    timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with event_bus._lock:  # noqa: SLF001
            buf = event_bus._buffers.get(job_id)  # noqa: SLF001
            if buf is None:
                # Already streamed + reaped → must be done. Caller checks
                # service-level state instead.
                return {"kind": "done"}
            done = buf.done
        if done:
            # Drain remaining events to find the terminal one.
            terminal = None
            try:
                while True:
                    e = buf.queue.get_nowait()
                    if e["kind"] in event_bus.SENTINEL_KINDS:
                        terminal = e
            except Exception:
                pass
            return terminal or {"kind": "done"}
        time.sleep(0.05)
    return None


# ── /api/dedup/build-index ──────────────────────────────────────────────────
def test_build_index_returns_job_id(client: TestClient, tmp_path: Path):
    history_dir = tmp_path / "history"
    _seed_corpus(history_dir, ("a.md", "x" * 100))
    client.patch("/api/config", json={"dedup_history_dir": str(history_dir)})

    resp = client.post("/api/dedup/build-index", json={"kind": "history"})
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["stream_url"] == f"/api/events/{data['job_id']}"
    _wait_for_job_done(data["job_id"], timeout=5.0)


def test_build_index_completes_and_indexes_docs(client: TestClient, tmp_path: Path):
    history_dir = tmp_path / "history"
    # 25 docs so progress_cb fires (it ticks every 10 done).
    _seed_corpus(history_dir, *[(f"doc{i}.md", f"content {i} " + "y" * 60) for i in range(25)])
    client.patch("/api/config", json={"dedup_history_dir": str(history_dir)})

    job_id = client.post("/api/dedup/build-index", json={"kind": "history"}).json()["job_id"]
    terminal = _wait_for_job_done(job_id, timeout=15.0)
    assert terminal is not None and terminal["kind"] == "done"
    # Service-level state confirms the build landed.
    status = client.get("/api/dedup/status").json()
    assert status["history"]["doc_count"] >= 1


def test_build_index_with_missing_root_fails(client: TestClient, tmp_path: Path):
    # No dedup_history_dir set → service raises ValueError → bus.fail.
    job_id = client.post("/api/dedup/build-index", json={"kind": "history"}).json()["job_id"]
    terminal = _wait_for_job_done(job_id, timeout=3.0)
    assert terminal is not None
    assert terminal["kind"] == "error"
    assert "dedup_history_dir" in terminal["error"]


def test_build_index_invalid_kind_422(client: TestClient):
    resp = client.post("/api/dedup/build-index", json={"kind": "nope"})
    assert resp.status_code == 422


# ── /api/dedup/analyze ──────────────────────────────────────────────────────
def test_analyze_with_no_index_returns_empty_report(client: TestClient):
    resp = client.post("/api/dedup/analyze", json={
        "text": "x" * 200,
        "kind": "history",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["corpus_kind"] == "history"
    assert data["duplicate_chars"] == 0
    assert data["duplicate_ratio"] == 0.0
    assert data["hits"] == []


def test_analyze_after_build_finds_duplicates(client: TestClient, tmp_path: Path):
    history_dir = tmp_path / "history"
    repeated = "完全相同的一段中文内容会被查重命中。" * 20  # > 50 chars
    _seed_corpus(history_dir, ("a.md", repeated))
    client.patch("/api/config", json={"dedup_history_dir": str(history_dir)})

    job_id = client.post("/api/dedup/build-index", json={"kind": "history"}).json()["job_id"]
    _wait_for_job_done(job_id, timeout=10.0)

    resp = client.post("/api/dedup/analyze", json={
        "text": repeated,
        "kind": "history",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["duplicate_ratio"] > 0.5
    assert data["text_length"] == len(repeated)
    assert len(data["top_matches"]) >= 1


def test_analyze_invalid_kind_422(client: TestClient):
    resp = client.post("/api/dedup/analyze", json={"text": "hi", "kind": "nope"})
    assert resp.status_code == 422


# ── /api/dedup/status ───────────────────────────────────────────────────────
def test_status_returns_zero_doc_count_when_unbuilt(client: TestClient):
    resp = client.get("/api/dedup/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["history"]["doc_count"] == 0
    assert data["vault"]["doc_count"] == 0


# ── /api/keyword/density ────────────────────────────────────────────────────
def test_density_basic(client: TestClient):
    resp = client.post("/api/keyword/density", json={
        "keyword": "无线吸尘器",
        "text": "无线吸尘器选购指南。无线吸尘器哪款好？无线吸尘器的功率是关键指标。",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert data["density"] > 0.4
    assert data["density"] < 0.5
    assert data["keyword_length"] == 5


def test_density_keyword_absent(client: TestClient):
    resp = client.post("/api/keyword/density", json={
        "keyword": "扫地机器人",
        "text": "无线吸尘器选购指南。",
    })
    assert resp.json() == {
        "count": 0,
        "density": 0.0,
        "text_length": 10,
        "keyword_length": 5,
    }


def test_density_empty_text_or_keyword_422(client: TestClient):
    """Pydantic min_length=1 catches empty strings before the service runs."""
    assert client.post("/api/keyword/density", json={"keyword": "", "text": "x"}).status_code == 422
    assert client.post("/api/keyword/density", json={"keyword": "x", "text": ""}).status_code == 422
