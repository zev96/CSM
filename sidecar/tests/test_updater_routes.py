"""Tests for /api/updater/*.

The check endpoint is sync and easy. The download endpoint is wrapped in
SSE — same as dedup, we drive it via the service and poll the EventBus
internal state rather than fight TestClient + EventSourceResponse.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_sidecar.event_bus import bus as event_bus
from csm_sidecar.services import updater_service


def _wait_for_job_done(job_id: str, timeout: float = 5.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with event_bus._lock:  # noqa: SLF001
            buf = event_bus._buffers.get(job_id)  # noqa: SLF001
            if buf is None:
                return {"kind": "done"}
            done = buf.done
        if done:
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


# ── /api/updater/check ──────────────────────────────────────────────────────
def test_check_uses_default_repo_when_unset(client: TestClient, monkeypatch):
    """No update_repo configured → fall back to DEFAULT_UPDATE_REPO.

    Out-of-the-box users shouldn't need to edit settings.json to get
    update checks. We verify by intercepting the underlying client call
    and asserting the default constant was passed through.
    """
    seen: dict[str, str] = {}
    from csm_core.updater_client.checker import CheckResult

    def fake_check(*, repo, token, current_version, timeout):
        seen["repo"] = repo
        return CheckResult(False, None, None)

    monkeypatch.setattr("csm_sidecar.services.updater_service.check_for_update", fake_check)
    resp = client.get("/api/updater/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_update"] is False
    assert data["error"] is None
    assert data["current_version"]  # comes from csm_sidecar.__version__
    # default constant lives in updater_service — match by content not import
    assert seen["repo"] == "zev96/CSM"


def test_check_propagates_github_failure(client: TestClient, monkeypatch):
    """When the repo is set but GitHub returns an error, surface it."""
    client.patch("/api/config", json={"update_repo": "definitely/does-not-exist-xyz"})

    from csm_core.updater_client.checker import CheckResult

    def fake_check(*, repo, token, current_version, timeout):
        return CheckResult(False, None, "not found: 404")

    monkeypatch.setattr("csm_sidecar.services.updater_service.check_for_update", fake_check)
    resp = client.get("/api/updater/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_update"] is False
    assert "not found" in data["error"]


def test_check_returns_update_info_when_newer(client: TestClient, monkeypatch):
    client.patch("/api/config", json={"update_repo": "anyone/anyrepo"})
    from csm_core.updater_client.checker import CheckResult
    from csm_core.updater_client.manifest import UpdateInfo
    info = UpdateInfo(
        version="9.9.9", tag_name="v9.9.9",
        zip_url="https://example.com/x.zip",
        manifest_url="https://example.com/m.json",
        changelog="all-new",
        published_at="2026-05-09T00:00:00Z",
        asset_size=12345,
    )

    def fake_check(*, repo, token, current_version, timeout):
        return CheckResult(True, info, None)

    monkeypatch.setattr("csm_sidecar.services.updater_service.check_for_update", fake_check)
    data = client.get("/api/updater/check").json()
    assert data["has_update"] is True
    assert data["info"]["version"] == "9.9.9"
    assert data["error"] is None


# ── /api/updater/download ───────────────────────────────────────────────────
def test_download_validates_sha256_length(client: TestClient):
    """Pydantic min/max_length=64 rejects malformed sha values."""
    resp = client.post("/api/updater/download", json={
        "url": "https://example.com/x.zip",
        "expected_sha256": "abc",  # too short
    })
    assert resp.status_code == 422


def test_download_returns_job_id_and_streams_failure(client: TestClient, monkeypatch):
    """Service accepts the job, worker fails (URL unreachable), error event lands on bus."""
    def boom(*args, **kwargs):
        from csm_core.updater_client.downloader import DownloadError
        raise DownloadError("simulated failure")

    monkeypatch.setattr("csm_sidecar.services.updater_service.download_with_verification", boom)
    resp = client.post("/api/updater/download", json={
        "url": "https://example.com/update.zip",
        "expected_sha256": "0" * 64,
    })
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    terminal = _wait_for_job_done(data["job_id"], timeout=3.0)
    assert terminal is not None
    assert terminal["kind"] == "error"
    assert "simulated failure" in terminal["error"]


def test_download_success_publishes_done(client: TestClient, monkeypatch, tmp_path):
    """Verify the success path — bus.finish gets called with sha + target."""
    def fake_download(*, url, target, expected_sha256, progress_cb=None, **kwargs):
        # Simulate a small write so bus.finish runs.
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
        if progress_cb:
            progress_cb(4, 4)
        return expected_sha256  # claim verification passed

    monkeypatch.setattr("csm_sidecar.services.updater_service.download_with_verification", fake_download)
    resp = client.post("/api/updater/download", json={
        "url": "https://example.com/asset.zip",
        "expected_sha256": "a" * 64,
    })
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    terminal = _wait_for_job_done(job_id, timeout=3.0)
    assert terminal is not None
    assert terminal["kind"] == "done"
    assert terminal["sha256"] == "a" * 64
    assert terminal["target"].endswith("asset.zip")
