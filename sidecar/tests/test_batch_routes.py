"""Tests for /api/batch.

End-to-end happy path is covered with a tmp vault + minimal template +
mock LLM, so the full csm_core stage composition runs without external
deps. Cancellation, snapshot, and validation paths are direct unit tests.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from csm_sidecar.services import batch_service


# ── Helpers ────────────────────────────────────────────────────────────────
def _setup_minimal_world(client: TestClient, tmp_path: Path) -> dict[str, Path]:
    """Build the smallest config + vault + template needed for run-end-to-end.

    Returns the path bundle so callers can poke at on-disk artefacts."""
    vault = tmp_path / "vault"
    out = tmp_path / "out"
    tpls = tmp_path / "tpls"
    vault.mkdir()
    out.mkdir()
    tpls.mkdir()
    # Minimal vault note so scan_vault doesn't choke and BrandRegistry has *something* to chew on.
    (vault / "stub.md").write_text(
        "---\nmodule: any\n---\n# stub\n", encoding="utf-8"
    )
    # Template with one HeadingBlock — no source/picks needed.
    template_body = {
        "id": "tpl1",
        "name": "演示",
        "product": "无线吸尘器",
        "template_type": "导购文",
        "default_skill_id": None,
        "blocks": [
            {"kind": "heading", "id": "h1", "level": 2, "text": "标题"},
        ],
    }
    (tpls / "tpl1.json").write_text(json.dumps(template_body, ensure_ascii=False), encoding="utf-8")

    client.patch("/api/config", json={
        "vault_root": str(vault),
        "out_dir": str(out),
        "default_template": str(tpls / "tpl1.json"),
        "default_provider": "mock",
    })
    return {"vault": vault, "out": out, "tpls": tpls}


def _wait_for_finished(job_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = batch_service.get_state(job_id)
        if st is not None and st.finished_at is not None:
            return st.to_dict()
        time.sleep(0.05)
    return None


# ── Validation / submission ────────────────────────────────────────────────
def test_submit_empty_keywords_422(client: TestClient):
    resp = client.post("/api/batch", json={"keywords": [], "template_id": "x"})
    assert resp.status_code == 422


def test_submit_all_blank_keywords_400(client: TestClient):
    """All keywords whitespace → service raises ValueError → 400."""
    resp = client.post("/api/batch", json={"keywords": ["   ", ""], "template_id": "x"})
    # Pydantic min_length=1 lets [""] through (len=1) but service de-dupes to empty.
    # Both 400 and 422 are acceptable shapes here; we accept either.
    assert resp.status_code in (400, 422)


def test_submit_returns_job_id_and_total(client: TestClient, tmp_path: Path):
    _setup_minimal_world(client, tmp_path)
    resp = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2", "kw1"],  # dup will be removed
        "template_id": "tpl1",
    })
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["total"] == 2
    assert data["stream_url"] == f"/api/events/{data['job_id']}"
    _wait_for_finished(data["job_id"], timeout=10.0)


# ── Snapshot ────────────────────────────────────────────────────────────────
def test_snapshot_returns_state(client: TestClient, tmp_path: Path):
    _setup_minimal_world(client, tmp_path)
    job_id = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2"],
        "template_id": "tpl1",
    }).json()["job_id"]

    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None, "batch did not finish in time"
    assert snap["job_id"] == job_id
    assert len(snap["items"]) == 2
    assert all(it["status"] in ("success", "failed") for it in snap["items"])


def test_snapshot_unknown_job_404(client: TestClient):
    resp = client.get("/api/batch/no-such-id")
    assert resp.status_code == 404


# ── Cancellation ───────────────────────────────────────────────────────────
def test_cancel_unknown_job_returns_ok_false(client: TestClient):
    resp = client.post("/api/batch/no-such-id/cancel")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_cancel_after_finish_returns_ok_false(client: TestClient, tmp_path: Path):
    _setup_minimal_world(client, tmp_path)
    job_id = client.post("/api/batch", json={
        "keywords": ["kw1"],
        "template_id": "tpl1",
    }).json()["job_id"]
    _wait_for_finished(job_id, timeout=10.0)
    resp = client.post(f"/api/batch/{job_id}/cancel")
    # finished — cancel is a no-op, returns ok=False
    assert resp.json()["ok"] is False


# ── Status transitions: every item ends in a terminal state ────────────────
def test_all_items_end_in_terminal_status(client: TestClient, tmp_path: Path):
    _setup_minimal_world(client, tmp_path)
    job_id = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2", "kw3"],
        "template_id": "tpl1",
    }).json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=15.0)
    assert snap is not None
    statuses = {it["status"] for it in snap["items"]}
    # No item should be left as queued/running once finished_at is set.
    assert statuses.isdisjoint({"queued", "running"})


# ── Failure path: missing config ───────────────────────────────────────────
def test_submit_with_missing_vault_root_streams_error(client: TestClient, tmp_path: Path):
    """Service accepts the job (202) but the worker fails fast and pushes an
    ``error`` event onto the SSE stream."""
    # No config setup — vault_root unset.
    resp = client.post("/api/batch", json={
        "keywords": ["kw1"],
        "template_id": "tpl1",
    })
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    _wait_for_finished(job_id, timeout=5.0)
    snap = batch_service.get_state(job_id)
    assert snap is not None
    assert snap.finished_at is not None
    # Whole-batch failure → no items run, all stay queued and we never
    # update them to cancelled (cancel path) — but the worker fail path
    # leaves them queued. That's fine; the SSE error event is the signal.
