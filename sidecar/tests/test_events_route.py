"""Tests for the generic ``GET /api/events/{job_id}`` SSE stream.

The stream now lives in routes/updater.py (the updater download is its
only remaining consumer). We only exercise the wiring here — a job_id
nobody registered must come back as a terminal ``error`` event instead
of hanging the client.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


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
