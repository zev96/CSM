"""Route tests for /api/mining/*. Uses existing client + monitor_db fixtures."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import mining_service


@pytest.fixture(autouse=True)
def reset_mining_service(monitor_db: Path):
    """Reset service singletons so each test starts clean.

    Depends on monitor_db so the DB is initialized before mining_service.init()
    calls mark_interrupted_jobs().
    """
    mining_service._executor = None
    mining_service._runner = None
    mining_service._active_job_id = None
    mining_service.init()
    yield
    mining_service.shutdown()
    mining_service._executor = None
    mining_service._runner = None
    mining_service._active_job_id = None


def test_list_videos_empty(client: TestClient, monitor_db: Path):
    r = client.get("/api/mining/videos")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_start_job_rejects_invalid_target(client: TestClient, monitor_db: Path):
    r = client.post("/api/mining/jobs", json={"keyword": "k", "target_per_platform": 5})
    assert r.status_code == 422  # below ge=10


def test_start_job_rejects_empty_keyword(client: TestClient, monitor_db: Path):
    r = client.post("/api/mining/jobs", json={"keyword": ""})
    assert r.status_code == 422


def test_cancel_unknown_job_returns_409(client: TestClient, monitor_db: Path):
    r = client.post("/api/mining/jobs/9999/cancel")
    assert r.status_code == 409


def test_videos_commented_query_three_values(client: TestClient, monitor_db: Path):
    # Insert two videos manually.
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, already_commented) "
        "VALUES('douyin','x','u',1)"
    )
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) "
        "VALUES('douyin','y','u2')"
    )
    r0 = client.get("/api/mining/videos?commented=0")
    r1 = client.get("/api/mining/videos?commented=1")
    rall = client.get("/api/mining/videos?commented=all")
    assert r0.json()["total"] == 1
    assert r1.json()["total"] == 1
    assert rall.json()["total"] == 2


def test_export_csv_returns_attachment(client: TestClient, monitor_db: Path):
    r = client.get("/api/mining/videos/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert r.text.startswith("﻿")  # BOM
    assert "platform,video_id,url" in r.text


def test_login_status_returns_three_platforms(client: TestClient, monitor_db: Path, tmp_path):
    from csm_core.browser_infra import mining_browser
    mining_browser.configure_profile_root(tmp_path / "profiles")
    r = client.get("/api/mining/login/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"douyin", "bilibili", "kuaishou"}
    for p, info in body.items():
        assert info["logged_in"] is False  # fresh profiles


def test_soft_delete_nonexistent_returns_404(client: TestClient, monitor_db: Path):
    r = client.delete("/api/mining/videos/9999")
    assert r.status_code == 404
