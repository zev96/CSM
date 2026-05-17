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


# ── Phase 2/3 export.csv enhancements (T12) ──────────────────────────
def _parse_csv_response(text: str) -> tuple[list[str], list[list[str]]]:
    """Strip BOM + parse CSV body. Returns (header, data_rows)."""
    import csv as _csv
    import io as _io
    body = text.lstrip("﻿")
    reader = _csv.reader(_io.StringIO(body))
    rows = list(reader)
    return rows[0], rows[1:]


def _insert_video(platform: str = "douyin", pid: str = "vid1", url: str = "u") -> int:
    conn = monitor_storage.get_conn()
    cur = conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title, author_name) "
        "VALUES(?,?,?,?,?) RETURNING id",
        (platform, pid, url, f"title-{pid}", f"author-{pid}"),
    )
    return int(cur.fetchone()[0])


def test_export_csv_no_comments_no_ai_summary_backward_compatible(
    client: TestClient, monitor_db: Path,
):
    """No comments, no ai_summary → only the new ai_summary column gets
    appended; no comment_tier_N columns at all (max_tier=0)."""
    _insert_video()
    r = client.get("/api/mining/videos/export.csv")
    assert r.status_code == 200
    header, data = _parse_csv_response(r.text)
    assert "ai_summary" in header
    assert header[-1] == "ai_summary"  # no tier cols appended
    assert not any(h.startswith("comment_tier_") for h in header)
    assert not any(h.startswith("images_tier_") for h in header)
    assert len(data) == 1
    # ai_summary column should be empty
    assert data[0][header.index("ai_summary")] == ""


def test_export_csv_ai_summary_populated(client: TestClient, monitor_db: Path):
    vid = _insert_video()
    ms.set_ai_summary(vid, "这是 AI 速览文本")
    r = client.get("/api/mining/videos/export.csv")
    header, data = _parse_csv_response(r.text)
    assert data[0][header.index("ai_summary")] == "这是 AI 速览文本"


def test_export_csv_one_comment_one_video_two_videos(
    client: TestClient, monitor_db: Path,
):
    """One video has a tier-1 comment, another has none. Header has
    comment_tier_1 + images_tier_1; the second video's row leaves them
    empty."""
    v1 = _insert_video(pid="a")
    v2 = _insert_video(pid="b")
    ms.create_comment(v1, tier=1, text="hello", image_ids=["img-x", "img-y"])

    r = client.get("/api/mining/videos/export.csv")
    header, data = _parse_csv_response(r.text)
    assert "comment_tier_1" in header
    assert "images_tier_1" in header
    assert "comment_tier_2" not in header

    rows_by_pid = {row[header.index("video_id")]: row for row in data}
    a_row = rows_by_pid["a"]
    b_row = rows_by_pid["b"]
    assert a_row[header.index("comment_tier_1")] == "hello"
    assert a_row[header.index("images_tier_1")] == "images/img-x,images/img-y"
    assert b_row[header.index("comment_tier_1")] == ""
    assert b_row[header.index("images_tier_1")] == ""


def test_export_csv_skipping_tier_keeps_intermediate_empty(
    client: TestClient, monitor_db: Path,
):
    """Tier 1 and tier 3 present, tier 2 missing → header still includes
    comment_tier_2 + images_tier_2 (empty), comment_tier_3 + images_tier_3
    populated."""
    v1 = _insert_video(pid="a")
    ms.create_comment(v1, tier=1, text="t1", image_ids=["i1"])
    ms.create_comment(v1, tier=3, text="t3", image_ids=["i3a", "i3b"])

    r = client.get("/api/mining/videos/export.csv")
    header, data = _parse_csv_response(r.text)
    for col in (
        "comment_tier_1", "images_tier_1",
        "comment_tier_2", "images_tier_2",
        "comment_tier_3", "images_tier_3",
    ):
        assert col in header
    row = data[0]
    assert row[header.index("comment_tier_1")] == "t1"
    assert row[header.index("images_tier_1")] == "images/i1"
    assert row[header.index("comment_tier_2")] == ""
    assert row[header.index("images_tier_2")] == ""
    assert row[header.index("comment_tier_3")] == "t3"
    assert row[header.index("images_tier_3")] == "images/i3a,images/i3b"


def test_export_csv_ids_filter(client: TestClient, monitor_db: Path):
    """?ids=1,3 exports only those videos, regardless of the
    already_commented filter (which defaults to "uncommented only")."""
    v1 = _insert_video(pid="a")
    v2 = _insert_video(pid="b")
    v3 = _insert_video(pid="c")
    # v2 is "already commented" — would normally be excluded by the
    # default commented=0 filter, but ?ids overrides that.
    monitor_storage.get_conn().execute(
        "UPDATE videos SET already_commented=1 WHERE id=?", (v2,),
    )

    r = client.get(f"/api/mining/videos/export.csv?ids={v1},{v3}")
    header, data = _parse_csv_response(r.text)
    pids = {row[header.index("video_id")] for row in data}
    assert pids == {"a", "c"}

    # ids list including the commented one also works.
    r2 = client.get(f"/api/mining/videos/export.csv?ids={v1},{v2},{v3}")
    _, data2 = _parse_csv_response(r2.text)
    pids2 = {row[header.index("video_id")] for row in data2}
    assert pids2 == {"a", "b", "c"}


def test_export_csv_ids_only_considers_selected_videos_for_max_tier(
    client: TestClient, monitor_db: Path,
):
    """max_tier should be computed from the selected video set, not the
    whole DB — otherwise an unrelated video with 5 tiers would balloon
    the header for an ids=... export."""
    v1 = _insert_video(pid="a")
    v2 = _insert_video(pid="b")
    ms.create_comment(v1, tier=1, text="t1")
    ms.create_comment(v2, tier=1, text="x1")
    ms.create_comment(v2, tier=2, text="x2")
    ms.create_comment(v2, tier=3, text="x3")

    # Only ask for v1 → max_tier should be 1, header has 1 pair only.
    r = client.get(f"/api/mining/videos/export.csv?ids={v1}")
    header, _ = _parse_csv_response(r.text)
    assert "comment_tier_1" in header
    assert "comment_tier_2" not in header
    assert "comment_tier_3" not in header


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
