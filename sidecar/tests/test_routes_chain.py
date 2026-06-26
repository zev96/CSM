"""Unit B2: POST /api/chain/rerun 路由 + GenerateBody.skill_chain 透传 + seed 平台 skill。

rerun 200（缓存命中重跑）/404（未知 job）/400（pass_index 越界）；
generate 接受 skill_chain 并透传到服务层；
examples/skills/小红书适配.md 被 list_skills 解析为 role=platform。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from csm_sidecar.services import chain_service, generate_service, skills_service


def _seed_chain(job_id: str = "j-route", monkeypatch=None):
    """跑一条 2 步链进缓存（fake client），供 rerun 命中。"""
    chain_service.reset_for_test()

    class _Seq:
        def __init__(self):
            self.n = 0

        def complete(self, *, system, user, temperature=None):
            self.n += 1
            return f"OUT[{self.n}]"

    steps = [
        chain_service.ChainStepInput(skill_id="p", role="persona", name="人设", body="P"),
        chain_service.ChainStepInput(skill_id="h", role="humanize", name="去AI味", body="H"),
    ]
    chain_service.run_chain(
        job_id, steps, draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=_Seq(),
        checkpoint=lambda: None, on_pass=lambda p: None,
    )


def test_rerun_200_returns_passes_and_final(client: TestClient, monkeypatch):
    _seed_chain("j-ok")
    # rerun 时 client=None → 走 build_client；patch 成确定性序列
    monkeypatch.setattr(chain_service.llm_factory, "build_client",
                        lambda **k: type("C", (), {
                            "complete": staticmethod(lambda *, system, user, temperature=None: "RR"),
                        })())
    resp = client.post("/api/chain/rerun", json={"job_id": "j-ok", "pass_index": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["passes"]) == 2
    assert data["passes"][1]["output"] == "RR"
    assert data["final_text"] == data["passes"][-1]["output"]
    assert data["cost"]["currency"] == "CNY"


def test_rerun_404_unknown_job(client: TestClient):
    chain_service.reset_for_test()
    resp = client.post("/api/chain/rerun", json={"job_id": "nope", "pass_index": 0})
    assert resp.status_code == 404


def test_rerun_400_index_out_of_range(client: TestClient):
    _seed_chain("j-oor")
    resp = client.post("/api/chain/rerun", json={"job_id": "j-oor", "pass_index": 9})
    assert resp.status_code == 400


def test_rerun_422_negative_index(client: TestClient):
    resp = client.post("/api/chain/rerun", json={"job_id": "x", "pass_index": -1})
    assert resp.status_code == 422


def test_generate_accepts_skill_chain(client: TestClient, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit",
                        lambda req: captured.update(req=req) or "job-sc")
    body = {
        "keyword": "无线吸尘器", "template_id": "t",
        "skill_chain": ["人设", "去味", "小红书适配"],
    }
    resp = client.post("/api/generate", json=body)
    assert resp.status_code == 202
    assert captured["req"].skill_chain == ["人设", "去味", "小红书适配"]


def test_generate_without_skill_chain_zero_regression(client: TestClient, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit",
                        lambda req: captured.update(req=req) or "job-nc")
    resp = client.post("/api/generate", json={"keyword": "k", "template_id": "t"})
    assert resp.status_code == 202
    assert captured["req"].skill_chain is None


def test_seed_xhs_skill_parses_as_platform(tmp_path: Path):
    """examples/skills/小红书适配.md → list_skills 解析 role=platform。

    examples/ 不是运行时 skill_dir（运行时在 %LOCALAPPDATA%）；这里把 seed
    拷进 tmp 当 skill_dir 验证它能被正确解析。"""
    seed = Path(__file__).resolve().parents[2] / "examples" / "skills" / "小红书适配.md"
    assert seed.exists(), f"seed skill missing: {seed}"
    sdir = tmp_path / "skills"
    sdir.mkdir()
    shutil.copy(seed, sdir / "小红书适配.md")
    skills = {s.id: s for s in skills_service.list_skills(sdir)}
    assert "小红书适配" in skills
    assert skills["小红书适配"].role == "platform"
    assert skills["小红书适配"].body.strip()  # body 非空
