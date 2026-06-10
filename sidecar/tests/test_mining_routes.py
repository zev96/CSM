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
    assert r.text.startswith("﻿")  # BOM so Excel auto-detects UTF-8
    # 2026-05 重排：中文表头（给兼职人填返图）
    assert "序号,平台,视频链接" in r.text


# ── Phase 2/3 export.csv enhancements (T12) ──────────────────────────
def _parse_csv_response(text: str) -> tuple[list[str], list[list[str]]]:
    """Strip BOM + parse CSV body. Returns (header, data_rows)."""
    import csv as _csv
    import io as _io
    body = text.lstrip("﻿")
    reader = _csv.reader(_io.StringIO(body))
    rows = list(reader)
    return rows[0], rows[1:]


def _tier_cols(tier: int) -> tuple[int, int, int]:
    """新版 CSV 布局 序号|平台|视频链接 + N×(内容|图片|返图) 下，
    1-based tier 的 (评论内容, 评论图片, 评论返图) 三列索引。
    列名按层重复，必须按位置定位而非 header.index。"""
    base = 3 + (tier - 1) * 3
    return base, base + 1, base + 2


def _insert_video(platform: str = "douyin", pid: str = "vid1", url: str = "u") -> int:
    conn = monitor_storage.get_conn()
    cur = conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title, author_name) "
        "VALUES(?,?,?,?,?) RETURNING id",
        (platform, pid, url, f"title-{pid}", f"author-{pid}"),
    )
    return int(cur.fetchone()[0])


def test_export_csv_no_comments_base_columns_only(
    client: TestClient, monitor_db: Path,
):
    """无评论 → max_tier=0 → 仅三列基础表头，不追加任何层列；
    ai_summary 已随 2026-05 重排从 CSV 下线。"""
    _insert_video()
    r = client.get("/api/mining/videos/export.csv")
    assert r.status_code == 200
    header, data = _parse_csv_response(r.text)
    assert header == ["序号", "平台", "视频链接"]
    assert not any(h.startswith("第") for h in header)
    assert "ai_summary" not in header
    assert len(data) == 1


def test_export_csv_excludes_ai_summary(client: TestClient, monitor_db: Path):
    """ai_summary 故意不进 CSV（对兼职人无用、徒增列宽）—— 守护这个有意排除。"""
    vid = _insert_video()
    ms.set_ai_summary(vid, "这是 AI 速览文本")
    r = client.get("/api/mining/videos/export.csv")
    header, _ = _parse_csv_response(r.text)
    assert "ai_summary" not in header
    assert "这是 AI 速览文本" not in r.text


def test_export_csv_one_comment_one_video_two_videos(
    client: TestClient, monitor_db: Path,
):
    """一个视频有 tier-1 评论、另一个没有。表头含 第1层 三连列、无第2层；
    没评论的那行三列留空；评论返图永远空。"""
    v1 = _insert_video(pid="a", url="ua")
    _insert_video(pid="b", url="ub")
    ms.create_comment(v1, tier=1, text="hello", image_ids=["img-x", "img-y"])

    r = client.get("/api/mining/videos/export.csv")
    header, data = _parse_csv_response(r.text)
    assert "第1层评论内容" in header
    assert "评论图片" in header
    assert "评论返图" in header
    assert "第2层评论内容" not in header

    rows_by_url = {row[2]: row for row in data}  # 列 2 = 视频链接
    a_row = rows_by_url["ua"]
    b_row = rows_by_url["ub"]
    content, images, refimg = _tier_cols(1)
    assert a_row[content] == "hello"
    assert a_row[images] == "images/img-x,images/img-y"
    assert a_row[refimg] == ""           # 评论返图永远空
    assert b_row[content] == ""
    assert b_row[images] == ""


def test_export_csv_skipping_tier_keeps_intermediate_empty(
    client: TestClient, monitor_db: Path,
):
    """tier 1、3 有评论，tier 2 没有 → 表头仍含 第1/2/3层三连列，
    第2层留空，第1/3层有值。"""
    v1 = _insert_video(pid="a", url="ua")
    ms.create_comment(v1, tier=1, text="t1", image_ids=["i1"])
    ms.create_comment(v1, tier=3, text="t3", image_ids=["i3a", "i3b"])

    r = client.get("/api/mining/videos/export.csv")
    header, data = _parse_csv_response(r.text)
    assert "第1层评论内容" in header
    assert "第2层评论内容" in header
    assert "第3层评论内容" in header
    row = data[0]
    c1, im1, _ = _tier_cols(1)
    c2, im2, _ = _tier_cols(2)
    c3, im3, _ = _tier_cols(3)
    assert row[c1] == "t1"
    assert row[im1] == "images/i1"
    assert row[c2] == ""
    assert row[im2] == ""
    assert row[c3] == "t3"
    assert row[im3] == "images/i3a,images/i3b"


def test_export_csv_ids_filter(client: TestClient, monitor_db: Path):
    """?ids=... 只导出选中视频，覆盖默认 commented=0 过滤。按 视频链接 keying。"""
    v1 = _insert_video(pid="a", url="ua")
    v2 = _insert_video(pid="b", url="ub")
    v3 = _insert_video(pid="c", url="uc")
    monitor_storage.get_conn().execute(
        "UPDATE videos SET already_commented=1 WHERE id=?", (v2,),
    )

    r = client.get(f"/api/mining/videos/export.csv?ids={v1},{v3}")
    header, data = _parse_csv_response(r.text)
    urls = {row[2] for row in data}
    assert urls == {"ua", "uc"}

    r2 = client.get(f"/api/mining/videos/export.csv?ids={v1},{v2},{v3}")
    _, data2 = _parse_csv_response(r2.text)
    urls2 = {row[2] for row in data2}
    assert urls2 == {"ua", "ub", "uc"}


def test_export_csv_ids_only_considers_selected_videos_for_max_tier(
    client: TestClient, monitor_db: Path,
):
    """max_tier 只按选中视频集算 —— 只要 v1 时表头只该有第1层。"""
    v1 = _insert_video(pid="a", url="ua")
    v2 = _insert_video(pid="b", url="ub")
    ms.create_comment(v1, tier=1, text="t1")
    ms.create_comment(v2, tier=1, text="x1")
    ms.create_comment(v2, tier=2, text="x2")
    ms.create_comment(v2, tier=3, text="x3")

    r = client.get(f"/api/mining/videos/export.csv?ids={v1}")
    header, _ = _parse_csv_response(r.text)
    assert "第1层评论内容" in header
    assert "第2层评论内容" not in header
    assert "第3层评论内容" not in header


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
