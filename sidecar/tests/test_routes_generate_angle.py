"""Unit B2.2: POST /api/generate 接 title/angle，且服务层收到 Angle 对象（非 dict）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from csm_core.angle import Angle
from csm_sidecar.services import generate_service


def test_generate_accepts_title_and_angle_object(client: TestClient, monkeypatch):
    captured: dict = {}

    def fake_submit(req):
        captured["req"] = req
        return "job-x"

    monkeypatch.setattr(generate_service, "submit", fake_submit)

    body = {
        "keyword": "无线吸尘器",
        "template_id": "t",
        "title": "无线吸尘器哪款好？",
        "angle": {"audience": "铲屎官", "sellpoints": ["防缠绕技术"], "tone": "口语"},
    }
    resp = client.post("/api/generate", json=body)
    assert resp.status_code == 202

    req = captured["req"]
    assert req.title == "无线吸尘器哪款好？"
    # 关键：angle 必须是 Angle 对象，不是 dict
    assert isinstance(req.angle, Angle)
    assert req.angle == Angle(audience="铲屎官", sellpoints=["防缠绕技术"], tone="口语")


def test_generate_without_angle_zero_regression(client: TestClient, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit",
                        lambda req: captured.update(req=req) or "job-y")
    resp = client.post("/api/generate", json={"keyword": "kw", "template_id": "t"})
    assert resp.status_code == 202
    req = captured["req"]
    assert req.title is None
    assert req.angle is None
    # 其余字段仍照常透传
    assert req.keyword == "kw" and req.template_id == "t"
