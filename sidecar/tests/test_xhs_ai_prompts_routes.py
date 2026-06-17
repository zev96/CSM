"""GET/PATCH /api/xhs/ai_prompts —— 夹具结构对齐 test_mining_ai_prompts_routes.py。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_get_shape_defaults_empty(client: TestClient, monitor_db: Path):
    r = client.get("/api/xhs/ai_prompts")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"generate", "polish"}
    assert data["generate"]["current"] == ""
    assert data["polish"]["current"] == ""
    assert data["generate"]["default"]   # 内置默认非空
    assert data["polish"]["default"]


def test_patch_persists_generate(client: TestClient, monitor_db: Path):
    r = client.patch("/api/xhs/ai_prompts", json={"generate": "自定义生成"})
    assert r.status_code == 200
    assert r.json()["generate"]["current"] == "自定义生成"
    assert client.get("/api/xhs/ai_prompts").json()["generate"]["current"] == "自定义生成"


def test_patch_empty_clears_back_to_default(client: TestClient, monitor_db: Path):
    client.patch("/api/xhs/ai_prompts", json={"polish": "x"})
    r = client.patch("/api/xhs/ai_prompts", json={"polish": ""})
    assert r.json()["polish"]["current"] == ""


def test_patch_no_fields_400(client: TestClient, monitor_db: Path):
    assert client.patch("/api/xhs/ai_prompts", json={}).status_code == 400


def test_patch_requires_auth(monitor_db: Path, settings_path: Path):
    """Strip the auth header and confirm 401."""
    from csm_sidecar.main import app
    with TestClient(app) as c:
        r = c.patch("/api/xhs/ai_prompts", json={"generate": "x"})
    assert r.status_code == 401
