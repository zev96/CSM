"""横评路由：POST /api/generate/comparison + finalize 404 预检放宽。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_comparison_endpoint_returns_job_and_stream(client, monkeypatch):
    from csm_sidecar.services import generate_service as gs
    monkeypatch.setattr(gs, "submit_comparison", lambda req: "jobC")
    resp = client.post("/api/generate/comparison", json={
        "models": ["A", "B"], "keyword": "怎么选", "tone": "口语",
    })
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "jobC"
    assert body["stream_url"] == "/api/events/jobC"


def test_comparison_endpoint_validates_models_min_two(client):
    resp = client.post("/api/generate/comparison", json={"models": ["A"]})
    assert resp.status_code == 422           # pydantic min_items=2


def test_comparison_endpoint_validates_models_max_four(client):
    resp = client.post("/api/generate/comparison",
                       json={"models": ["A", "B", "C", "D", "E"]})
    assert resp.status_code == 422           # max_items=4


def test_finalize_precheck_accepts_comparison_cache(client, monkeypatch):
    """横评缓存命中时 finalize 不应被 404 挡掉（plan 缓存 miss 也放行）。"""
    from csm_sidecar.services import generate_service as gs
    from csm_sidecar.services import comparison_cache as cc
    from csm_sidecar.services import assembler_service
    cc.reset_for_test()
    cc.cache_comparison("jobF", models=["A", "B"], category="吸尘器",
                        keyword="k", title=None, tone=None,
                        skill_chain=None, contract_mode=None)
    monkeypatch.setattr(assembler_service, "get_plan", lambda jid: None)  # plan miss
    monkeypatch.setattr(gs, "submit_finalize", lambda jid, req: jid)
    resp = client.post("/api/generate/jobF/finalize",
                       json={"draft": "edited", "keyword": "k"})
    assert resp.status_code == 202           # 横评缓存兜住，不 404
