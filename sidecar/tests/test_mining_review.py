"""P2 审核状态机测试：v14 迁移 + storage 审核函数 + 审核路由。

状态机（spec §4.1）：
  AI生成 → pending ──通过──→ approved ──同步(P3)──→ synced ──执行──→ executed
  人工/composer 创建的评论默认 approved，不进审核队列。
  编辑即背书：改了 pending 草稿的 text 并保存 → 自动 approved。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage


def _insert_video(*, video_id: int = 1, platform: str = "bilibili") -> int:
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url) VALUES(?,?,?,?)",
        (video_id, platform, f"vid-{video_id}", f"https://example/{video_id}"),
    )
    return video_id


# ── v14 迁移 ────────────────────────────────────────────────────────────

def test_v14_columns_exist(monitor_db: Path):
    conn = ms.get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(video_comments)").fetchall()}
    assert {"review_status", "template_id", "ai_flavor_score", "reviewed_at", "synced_at"} <= cols


def test_v14_migration_idempotent(monitor_db: Path):
    conn = ms.get_conn()
    ms.apply_v14_migration(conn)
    ms.apply_v14_migration(conn)


# ── storage：upsert_ai_comment ─────────────────────────────────────────

def test_upsert_ai_comment_insert_and_overwrite(monitor_db: Path):
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "v1", template_id=None, ai_flavor_score=2.5)
    c = ms.get_comment(cid)
    assert c["source"] == "ai_suggested"
    assert c["review_status"] == "pending"
    assert c["ai_flavor_score"] == 2.5

    # 重新生成 → 覆盖同一行（id 不变），分数/文本更新
    cid2 = ms.upsert_ai_comment(vid, 1, "v2", template_id=7, ai_flavor_score=0.0)
    assert cid2 == cid
    c2 = ms.get_comment(cid)
    assert c2["text"] == "v2"
    assert c2["template_id"] == 7
    assert c2["review_status"] == "pending"


def test_upsert_ai_comment_refuses_manual_tier(monitor_db: Path):
    vid = _insert_video()
    ms.create_comment(vid, 1, "人工写的")  # review_status 默认 approved
    with pytest.raises(ms.TierOccupiedError):
        ms.upsert_ai_comment(vid, 1, "ai text")


def test_upsert_ai_comment_refuses_approved_tier(monitor_db: Path):
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "v1")
    ms.approve_comment(cid)
    with pytest.raises(ms.TierOccupiedError):
        ms.upsert_ai_comment(vid, 1, "v2")


# ── storage：approve ───────────────────────────────────────────────────

def test_approve_comment_and_idempotency(monitor_db: Path):
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "text")
    c = ms.approve_comment(cid)
    assert c["review_status"] == "approved"
    assert c["reviewed_at"]

    # 幂等：再 approve 不变；对 executed 等状态也不动
    c2 = ms.approve_comment(cid)
    assert c2["review_status"] == "approved"


def test_approve_pending_for_videos_bulk(monitor_db: Path):
    v1, v2 = _insert_video(video_id=1), _insert_video(video_id=2)
    ms.upsert_ai_comment(v1, 1, "a")
    ms.upsert_ai_comment(v1, 2, "b")
    ms.upsert_ai_comment(v2, 1, "c")
    ms.create_comment(v2, 2, "manual")  # approved，不应被重复计数

    n = ms.approve_pending_for_videos([v1, v2])
    assert n == 3
    assert all(
        c["review_status"] == "approved"
        for vid in (v1, v2) for c in ms.list_comments(vid)
    )
    assert ms.approve_pending_for_videos([v1, v2]) == 0  # 再跑无 pending


def test_create_comment_defaults_approved(monitor_db: Path):
    vid = _insert_video()
    cid = ms.create_comment(vid, 1, "composer 写的", source="ai_suggested")
    assert ms.get_comment(cid)["review_status"] == "approved"


def test_list_videos_pending_review_count(monitor_db: Path):
    vid = _insert_video()
    ms.upsert_ai_comment(vid, 1, "a")
    ms.upsert_ai_comment(vid, 2, "b")
    rows, _ = ms.list_videos(commented="all")
    video = next(v for v in rows if v["id"] == vid)
    assert video["pending_review_count"] == 2

    ms.approve_pending_for_videos([vid])
    rows, _ = ms.list_videos(commented="all")
    video = next(v for v in rows if v["id"] == vid)
    assert video["pending_review_count"] == 0


# ── 路由 ────────────────────────────────────────────────────────────────

def test_review_route_approves(client: TestClient, monitor_db: Path):
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "text")
    r = client.patch(f"/api/mining/comments/{cid}/review", json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "approved"


def test_review_route_404(client: TestClient, monitor_db: Path):
    r = client.patch("/api/mining/comments/9999/review", json={"action": "approve"})
    assert r.status_code == 404


def test_review_route_rejects_unknown_action(client: TestClient, monitor_db: Path):
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "text")
    r = client.patch(f"/api/mining/comments/{cid}/review", json={"action": "reject"})
    assert r.status_code == 422  # pattern ^approve$ 校验失败


def test_review_bulk_route(client: TestClient, monitor_db: Path):
    v1 = _insert_video(video_id=1)
    ms.upsert_ai_comment(v1, 1, "a")
    ms.upsert_ai_comment(v1, 2, "b")
    r = client.post("/api/mining/comments/review_bulk", json={"video_ids": [v1]})
    assert r.status_code == 200
    assert r.json()["approved"] == 2


def test_patch_text_on_pending_auto_approves(client: TestClient, monitor_db: Path):
    """编辑即背书：改 pending 草稿的文案并保存 → 自动 approved。"""
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "AI 草稿")
    r = client.patch(f"/api/mining/comments/{cid}", json={"text": "人工改好的"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "人工改好的"
    assert body["review_status"] == "approved"


def test_patch_images_only_keeps_pending(client: TestClient, monitor_db: Path):
    """只换图不算内容背书：review_status 保持 pending。"""
    vid = _insert_video()
    cid = ms.upsert_ai_comment(vid, 1, "AI 草稿")
    r = client.patch(f"/api/mining/comments/{cid}", json={"image_ids": []})
    assert r.status_code == 200
    assert r.json()["review_status"] == "pending"
