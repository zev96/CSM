"""Unit B2.3: GET /api/angle/taxonomy — 角度受控词表只读端点（picker 数据源）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from csm_core.angle import taxonomy as t


def test_taxonomy_returns_full_vocab(client: TestClient):
    resp = client.get("/api/angle/taxonomy")
    assert resp.status_code == 200
    data = resp.json()

    # tones：3 个，每个 {key,hint}
    assert len(data["tones"]) == len(t.TONES) == 3
    assert {x["key"] for x in data["tones"]} == set(t.TONES)
    assert all(x["hint"].strip() for x in data["tones"])

    # dimensions：与词表一致（当前真实库校准为 10），每个 {key,label}
    assert len(data["dimensions"]) == len(t.SELLPOINT_DIMENSIONS)
    assert all(d["key"] and d["label"] for d in data["dimensions"])

    # audiences：16 名
    assert len(data["audiences"]) == 16
    assert set(data["audiences"]) == set(t.AUDIENCES)

    # presets：4 个，保留 name/audience/sellpoints/tone/template_id
    assert len(data["presets"]) == 4
    p0 = data["presets"][0]
    assert {"name", "template_id", "audience", "sellpoints", "tone"} <= set(p0)


def test_taxonomy_requires_auth():
    """无 token → 401/403（与其它路由一致，dependencies=[RequireToken]）。"""
    from csm_sidecar.main import app
    with TestClient(app) as c:
        resp = c.get("/api/angle/taxonomy")
    assert resp.status_code in (401, 403)
