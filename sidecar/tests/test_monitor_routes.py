"""Tests for /api/monitor/*.

These exercise the route + service layer against a per-test sqlite DB.
The MonitorLoop itself is NOT started here (the run-now route returns 503
when the loop is absent, and we test that path explicitly). The full
loop integration is covered by sidecar/tests/test_monitor_loop.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult


def _seed_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "zhihu_question",
        "name": "测试任务",
        "target_url": "https://www.zhihu.com/question/12345",
        "config": {"target_brand": "x", "top_n": 5},
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Storage gate ───────────────────────────────────────────────────────────
def test_routes_503_when_storage_uninitialized(settings_path, vault_cache_reset):
    """Accessing any monitor route without monitor_db fixture → 503."""
    from csm_sidecar import auth
    from csm_sidecar.main import app
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {auth.get_token()}"
        resp = c.get("/api/monitor/tasks")
    assert resp.status_code == 503
    assert "not initialised" in resp.json()["detail"]


# ── Task CRUD ──────────────────────────────────────────────────────────────
def test_create_list_get_update_delete(client: TestClient, monitor_db: Path):
    list_resp = client.get("/api/monitor/tasks")
    assert list_resp.status_code == 200
    assert list_resp.json() == {"count": 0, "tasks": []}

    tid = _seed_task(client, name="task1")
    assert tid > 0

    list2 = client.get("/api/monitor/tasks").json()
    assert list2["count"] == 1
    assert list2["tasks"][0]["name"] == "task1"

    get1 = client.get(f"/api/monitor/tasks/{tid}").json()
    assert get1["id"] == tid

    upd = client.patch(f"/api/monitor/tasks/{tid}", json={
        "type": "zhihu_question",
        "name": "renamed",
        "target_url": "https://www.zhihu.com/question/12345",
        "config": {"target_brand": "x", "top_n": 7},
        "schedule_cron": "08:00",
        "enabled": False,
    })
    assert upd.status_code == 200
    assert upd.json()["name"] == "renamed"
    assert upd.json()["enabled"] is False

    del_resp = client.delete(f"/api/monitor/tasks/{tid}")
    assert del_resp.status_code == 204
    assert client.get(f"/api/monitor/tasks/{tid}").status_code == 404


def test_create_invalid_type_422(client: TestClient, monitor_db: Path):
    resp = client.post("/api/monitor/tasks", json={
        "type": "not_a_type",
        "name": "x",
        "target_url": "x",
    })
    assert resp.status_code == 422


def test_get_unknown_task_404(client: TestClient, monitor_db: Path):
    assert client.get("/api/monitor/tasks/9999").status_code == 404


def test_list_filtered_by_type_and_enabled(client: TestClient, monitor_db: Path):
    _seed_task(client, name="zhi", type="zhihu_question")
    _seed_task(client, name="bili", type="bilibili_comment",
               target_url="https://www.bilibili.com/video/AV1")
    _seed_task(client, name="off", type="bilibili_comment",
               target_url="https://www.bilibili.com/video/AV2", enabled=False)

    bili = client.get("/api/monitor/tasks", params={"type": "bilibili_comment"}).json()
    assert bili["count"] == 2

    bili_on = client.get("/api/monitor/tasks", params={
        "type": "bilibili_comment", "enabled_only": True,
    }).json()
    assert bili_on["count"] == 1
    assert bili_on["tasks"][0]["name"] == "bili"


# ── Run-now ────────────────────────────────────────────────────────────────
def test_run_now_when_loop_not_started_returns_503(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    resp = client.post(f"/api/monitor/tasks/{tid}/run-now")
    assert resp.status_code == 503


def test_run_now_unknown_task_404(client: TestClient, monitor_db: Path, monkeypatch):
    """When the loop IS running, an unknown task_id is a 404."""
    from csm_sidecar.services import monitor_lifecycle
    from csm_sidecar.services.monitor_loop import MonitorLoop
    fake_loop = MonitorLoop(event_sink=lambda _e: None, adapters={})
    fake_loop.start()
    monkeypatch.setattr(monitor_lifecycle, "_loop", fake_loop)
    try:
        resp = client.post("/api/monitor/tasks/9999/run-now")
        assert resp.status_code == 404
    finally:
        fake_loop.stop()


# ── Results ────────────────────────────────────────────────────────────────
def test_list_results_empty(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    resp = client.get("/api/monitor/results", params={"task_id": tid})
    assert resp.status_code == 200
    assert resp.json() == {"task_id": tid, "count": 0, "results": []}


def test_list_results_returns_recent_first(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    # Seed 3 results directly via storage; route should return them ordered
    # newest first.
    for i in range(3):
        storage.save_result(MonitorResult(
            task_id=tid,
            checked_at=datetime.now() - timedelta(minutes=10 - i),
            status="ok",
            rank=i + 1,
            metric={"i": i},
        ))
    resp = client.get("/api/monitor/results", params={"task_id": tid, "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    # Most recent first: rank=3 (i=2) should be first.
    assert data["results"][0]["rank"] == 3


def test_list_results_limit_capped(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    resp = client.get("/api/monitor/results", params={"task_id": tid, "limit": 9999})
    # Pydantic Field(le=500) → 422 on out-of-range query.
    assert resp.status_code == 422


# ── Cookies ────────────────────────────────────────────────────────────────
def test_cookie_lifecycle(client: TestClient, monitor_db: Path):
    list_empty = client.get("/api/monitor/cookies", params={"platform": "zhihu_question"})
    assert list_empty.json()["count"] == 0

    add = client.post("/api/monitor/cookies/zhihu_question", json={
        "cookies_text": "z=1; auth=xxx",
        "label": "main account",
    })
    assert add.status_code == 201
    cred_id = add.json()["id"]

    listed = client.get("/api/monitor/cookies", params={"platform": "zhihu_question"})
    assert listed.json()["count"] == 1
    cookie = listed.json()["cookies"][0]
    assert cookie["label"] == "main account"
    # Sensitive fields stripped.
    assert "cookies_text" not in cookie
    assert "user_agent" not in cookie

    client.delete(f"/api/monitor/cookies/{cred_id}")
    assert client.get("/api/monitor/cookies", params={"platform": "zhihu_question"}).json()["count"] == 0


def test_cookie_add_empty_text_422(client: TestClient, monitor_db: Path):
    resp = client.post("/api/monitor/cookies/zhihu_question", json={
        "cookies_text": "",
        "label": "x",
    })
    assert resp.status_code == 422


# ── Summary ────────────────────────────────────────────────────────────────
def test_summary_empty(client: TestClient, monitor_db: Path):
    resp = client.get("/api/monitor/summary")
    assert resp.status_code == 200
    data = resp.json()
    # All four platform types present, each with task_count=0.
    assert set(data["platforms"].keys()) == {
        "zhihu_question", "bilibili_comment", "douyin_comment", "kuaishou_comment",
    }
    for p in data["platforms"].values():
        assert p["task_count"] == 0


def test_summary_includes_latest_result(client: TestClient, monitor_db: Path):
    tid = _seed_task(client, type="bilibili_comment",
                     target_url="https://www.bilibili.com/video/X")
    storage.save_result(MonitorResult(
        task_id=tid,
        checked_at=datetime.now(),
        status="ok",
        rank=2,
        metric={"retained": 8, "total": 10},
    ))
    summary = client.get("/api/monitor/summary").json()
    bili = summary["platforms"]["bilibili_comment"]
    assert bili["task_count"] == 1
    assert bili["tasks"][0]["latest"]["metric"]["retained"] == 8


# ── Auth ────────────────────────────────────────────────────────────────────
def test_monitor_routes_require_auth(monitor_db: Path):
    from csm_sidecar.main import app
    with TestClient(app) as c:
        # No Authorization header.
        resp = c.get("/api/monitor/tasks")
    assert resp.status_code == 401


# ── Baidu Keyword Monitor ──────────────────────────────────────────────────────
def test_create_baidu_keyword_task(client: TestClient, monitor_db: Path):
    body = {
        "type": "baidu_keyword",
        "name": "百度-Claude教程",
        "target_url": "search:Claude Code 教程",
        "config": {
            "search_keyword": "Claude Code 教程",
            "target_brands": ["Claude", "Anthropic"],
            "headless": True,
        },
        "schedule_cron": "manual",
        "enabled": True,
    }
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["type"] == "baidu_keyword"
    assert resp.json()["config"]["target_brands"] == ["Claude", "Anthropic"]
