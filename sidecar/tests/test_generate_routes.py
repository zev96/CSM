"""Tests for /api/generate + /api/events SSE.

The full pipeline depends on a real vault, real templates, and a working
LLM provider — far too heavy for unit tests. We exercise the *wiring*:
job submission, event streaming format, and failure propagation when
config is incomplete. End-to-end happy-path is covered by an integration
test (skipped by default) that needs a built vault and a mock LLM.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient


def test_generate_returns_job_id_and_stream_url(client: TestClient, tmp_path: Path):
    # No vault_root in config → worker fails fast, but the POST itself
    # should still 202 and return a job_id (we report the failure via SSE).
    body = {"keyword": "无线吸尘器", "template_id": "x"}
    resp = client.post("/api/generate", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["stream_url"] == f"/api/events/{data['job_id']}"


def test_generate_failure_streamed_as_error_event(client: TestClient, tmp_path: Path):
    # vault_root missing → expect an ``error`` event on the SSE stream.
    body = {"keyword": "kw", "template_id": "x"}
    job_id = client.post("/api/generate", json=body).json()["job_id"]
    joined = _drain_sse(client, f"/api/events/{job_id}", deadline_seconds=3.0)
    assert "event: error" in joined
    assert "vault_root" in joined  # error message mentions the missing field


def test_generate_invalid_body_422(client: TestClient):
    resp = client.post("/api/generate", json={"keyword": "", "template_id": "x"})
    assert resp.status_code == 422


def test_events_unknown_job_id_streams_error(client: TestClient):
    joined = _drain_sse(client, "/api/events/no-such-job", deadline_seconds=2.0)
    assert "event: error" in joined
    assert "unknown job_id" in joined


def _drain_sse(client: TestClient, url: str, *, deadline_seconds: float) -> str:
    """Read SSE lines until we see a terminal event (error/done) followed by
    its data line, or the deadline elapses. Returns all lines joined with \\n.

    SSE format is::

        event: error
        data: {"error": "..."}
        <blank line>

    so naively breaking on the ``event:`` line misses the payload. We track
    whether the most recent ``event:`` was a sentinel and break on the
    blank line that follows it.
    """
    raw: list[str] = []
    deadline = time.monotonic() + deadline_seconds
    last_event: str | None = None
    with client.stream("GET", url) as r:
        for line in r.iter_lines():
            raw.append(line)
            if line.startswith("event: "):
                last_event = line.removeprefix("event: ").strip()
            if line == "" and last_event in ("error", "done"):
                break
            if time.monotonic() > deadline:
                break
    return "\n".join(raw)


