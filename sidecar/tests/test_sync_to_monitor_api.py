"""HTTP endpoint tests for POST /api/mining/jobs/{job_id}/sync_to_monitor.

Uses --noconftest so all fixtures are defined inline (no conftest import).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage as monitor_storage
from csm_sidecar import auth
from csm_sidecar.main import app
from csm_sidecar.services import config_service


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def settings_path(tmp_path: Path):
    """Per-test settings.json — resets config_service singleton."""
    p = tmp_path / "settings.json"
    config_service.init(p)
    yield p
    config_service.init(None)


@pytest.fixture
def monitor_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test SQLite DB; resets monitor_storage module globals."""
    db_file = tmp_path / "monitor.db"
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(db_file)
    return db_file


@pytest.fixture
def client(settings_path: Path, monitor_db: Path):
    """Authenticated TestClient; token minted by the lifespan handler."""
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {auth.get_token()}"
        yield c


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_job(status: str = "done") -> int:
    """Insert a mining job directly; return its id."""
    conn = monitor_storage.get_conn()
    row = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw", json.dumps(["douyin"]), 10, status),
    ).fetchone()
    return int(row[0])


def _add_video_with_comment(job_id: int, pid: str, comment_text: str | None) -> int:
    """Insert a video linked to job_id; optionally add a tier=1 comment."""
    conn = monitor_storage.get_conn()
    video_id = int(conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) "
        "VALUES (?, ?, ?, ?) RETURNING id",
        ("douyin", pid, f"https://www.douyin.com/video/{pid}", f"title-{pid}"),
    ).fetchone()[0])
    conn.execute(
        "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
        "VALUES (?, ?, ?, ?)",
        (video_id, job_id, "kw", 0),
    )
    if comment_text is not None:
        conn.execute(
            "INSERT INTO video_comments(video_id, tier, text, status, source) "
            "VALUES (?, 1, ?, 'draft', 'manual')",
            (video_id, comment_text),
        )
    return video_id


_BODY = {"task_name_prefix": "test-prefix", "top_n": 5}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_sync_happy_path(client: TestClient, monitor_db: Path):
    """3 videos, all have tier-1 comments → created=3."""
    job_id = _create_job(status="done")
    _add_video_with_comment(job_id, "v1", "comment one")
    _add_video_with_comment(job_id, "v2", "comment two")
    _add_video_with_comment(job_id, "v3", "comment three")

    r = client.post(f"/api/mining/jobs/{job_id}/sync_to_monitor", json=_BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 3
    assert data["skipped_dup"] == 0
    assert data["skipped_no_draft"] == 0
    assert data["errors"] == []


def test_sync_404_unknown_job(client: TestClient, monitor_db: Path):
    """POST with a job_id that does not exist → 404."""
    r = client.post("/api/mining/jobs/9999/sync_to_monitor", json=_BODY)
    assert r.status_code == 404
    assert "未找到" in r.json()["detail"]


def test_sync_409_job_not_done(client: TestClient, monitor_db: Path):
    """Job still running → 409 (status not in done/partial_done)."""
    job_id = _create_job(status="running")
    r = client.post(f"/api/mining/jobs/{job_id}/sync_to_monitor", json=_BODY)
    assert r.status_code == 409
    assert "running" in r.json()["detail"]  # status echoed in the zh message


def test_sync_409_not_all_commented(client: TestClient, monitor_db: Path):
    """Job done but one video has no comment → 409."""
    job_id = _create_job(status="done")
    _add_video_with_comment(job_id, "v1", "has a comment")
    _add_video_with_comment(job_id, "v2", None)  # no comment

    r = client.post(f"/api/mining/jobs/{job_id}/sync_to_monitor", json=_BODY)
    assert r.status_code == 409
    assert "未填写评论" in r.json()["detail"]


def test_sync_422_top_n_zero(client: TestClient, monitor_db: Path):
    """top_n=0 violates ge=1 → 422 Pydantic validation error."""
    job_id = _create_job(status="done")
    r = client.post(
        f"/api/mining/jobs/{job_id}/sync_to_monitor",
        json={"task_name_prefix": "prefix", "top_n": 0},
    )
    assert r.status_code == 422


def test_sync_422_empty_prefix(client: TestClient, monitor_db: Path):
    """task_name_prefix="" violates min_length=1 → 422 Pydantic validation error."""
    job_id = _create_job(status="done")
    r = client.post(
        f"/api/mining/jobs/{job_id}/sync_to_monitor",
        json={"task_name_prefix": "", "top_n": 5},
    )
    assert r.status_code == 422


def _exclude_video(video_id: int) -> None:
    """Soft-delete a video (excluded=1), mirroring storage.soft_delete_video."""
    monitor_storage.get_conn().execute(
        "UPDATE videos SET excluded=1 WHERE id=?", (video_id,)
    )


def test_sync_excludes_soft_deleted_videos(client: TestClient, monitor_db: Path):
    """Soft-deleted (excluded=1) videos drop out of the total, so an
    all-commented job stays syncable after the user prunes the batch.

    2 commented videos + 1 soft-deleted uncommented video. Without the
    excluded filter the gate would see total=3 commented=2 → spurious 409.
    With it: total=2 commented=2 → 200, created=2 (the deleted one is never
    synced either).
    """
    job_id = _create_job(status="done")
    _add_video_with_comment(job_id, "v1", "comment one")
    _add_video_with_comment(job_id, "v2", "comment two")
    vid3 = _add_video_with_comment(job_id, "v3", None)  # no comment
    _exclude_video(vid3)

    r = client.post(f"/api/mining/jobs/{job_id}/sync_to_monitor", json=_BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 2
    assert data["skipped_no_draft"] == 0
