"""SSE event bus — placeholder for stage A3.

Replaces the QSignal/QThread fan-out the legacy GUI used to push pipeline
progress, monitor alerts, and batch task updates back to the UI. Each
long-running job opens an SSE stream keyed by its ``job_id``.

The actual implementation lands once the first streaming endpoint
(``/api/generate``) is wired in stage A3.
"""
from __future__ import annotations
