"""Task B: POST /api/generate/{job_id}/finalize 路由。

- 缓存 plan 缺失 → 404；
- 缓存 plan 命中 → 202，submit_finalize 收到重建的 FinalizeRequest（angle 单传）；
- 缺 draft / keyword → 422。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from csm_sidecar.services import assembler_service, generate_service


def test_finalize_404_when_no_cached_plan(client: TestClient):
    assembler_service.reset_for_test()
    resp = client.post("/api/generate/nope/finalize",
                       json={"draft": "毛坯", "keyword": "k"})
    assert resp.status_code == 404


def test_finalize_202_and_passes_request(client: TestClient, monkeypatch):
    monkeypatch.setattr(assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": object(), "template_id": "t", "seed": 0})())
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit_finalize",
                        lambda job_id, req: captured.update(job_id=job_id, req=req) or job_id)
    body = {
        "draft": "用户编辑后的初稿",
        "keyword": "无线吸尘器",
        "title": "无线吸尘器哪款好？",
        "angle": {"audience": "铲屎官", "sellpoints": ["防缠绕技术"], "tone": "口语"},
        "skill_chain": ["人设", "去味"],
    }
    resp = client.post("/api/generate/job-A/finalize", json=body)
    assert resp.status_code == 202
    assert resp.json()["job_id"] == "job-A"
    req = captured["req"]
    assert req.draft == "用户编辑后的初稿"
    assert req.keyword == "无线吸尘器"
    assert req.title == "无线吸尘器哪款好？"
    assert req.skill_chain == ["人设", "去味"]
    assert req.angle.audience == "铲屎官"
    assert req.angle.sellpoints == ["防缠绕技术"]


def test_finalize_422_missing_draft(client: TestClient, monkeypatch):
    monkeypatch.setattr(assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": object(), "template_id": "t", "seed": 0})())
    resp = client.post("/api/generate/job-A/finalize", json={"keyword": "k"})
    assert resp.status_code == 422


def test_finalize_422_missing_keyword(client: TestClient, monkeypatch):
    monkeypatch.setattr(assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": object(), "template_id": "t", "seed": 0})())
    resp = client.post("/api/generate/job-A/finalize", json={"draft": "毛坯"})
    assert resp.status_code == 422
