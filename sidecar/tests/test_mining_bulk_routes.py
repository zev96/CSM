"""Routes for bulk_mark_commented (Phase 2 T5)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.monitor import storage as monitor_storage


def _insert_videos(count: int = 3) -> list[int]:
    conn = monitor_storage.get_conn()
    ids: list[int] = []
    for i in range(1, count + 1):
        conn.execute(
            "INSERT INTO videos(id, platform, platform_video_id, url) VALUES(?,?,?,?)",
            (i, "bilibili", f"v-{i}", f"https://example/{i}"),
        )
        ids.append(i)
    return ids


def _commented_flags(ids: list[int]) -> list[int]:
    conn = monitor_storage.get_conn()
    rows = conn.execute(
        f"SELECT id, already_commented FROM videos WHERE id IN ({','.join('?'*len(ids))}) ORDER BY id",
        ids,
    ).fetchall()
    return [int(r["already_commented"]) for r in rows]


def test_bulk_mark_true_flips_all(client: TestClient, monitor_db: Path):
    ids = _insert_videos(3)
    r = client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": ids, "value": True},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 3}
    assert _commented_flags(ids) == [1, 1, 1]


def test_bulk_mark_false_reverses(client: TestClient, monitor_db: Path):
    ids = _insert_videos(3)
    client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": ids, "value": True},
    )
    r = client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": ids, "value": False},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 3}
    assert _commented_flags(ids) == [0, 0, 0]


def test_bulk_mark_empty_list_returns_zero(client: TestClient, monitor_db: Path):
    r = client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": [], "value": True},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 0}


def test_bulk_mark_stamps_metadata(client: TestClient, monitor_db: Path):
    """When marking true, commented_source='manual' and commented_at is set."""
    ids = _insert_videos(2)
    client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": ids, "value": True},
    )
    conn = monitor_storage.get_conn()
    rows = conn.execute(
        f"SELECT commented_source, commented_at FROM videos WHERE id IN ({','.join('?'*len(ids))})",
        ids,
    ).fetchall()
    for r in rows:
        assert r["commented_source"] == "manual"
        assert r["commented_at"]  # non-empty timestamp


def test_bulk_mark_false_clears_metadata(client: TestClient, monitor_db: Path):
    ids = _insert_videos(2)
    client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": ids, "value": True},
    )
    client.patch(
        "/api/mining/videos/bulk_mark_commented",
        json={"video_ids": ids, "value": False},
    )
    conn = monitor_storage.get_conn()
    rows = conn.execute(
        f"SELECT commented_source, commented_at FROM videos WHERE id IN ({','.join('?'*len(ids))})",
        ids,
    ).fetchall()
    for r in rows:
        assert r["commented_source"] is None
        assert r["commented_at"] is None
