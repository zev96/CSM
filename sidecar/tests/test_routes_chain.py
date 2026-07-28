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


def test_rerun_202_accepts_and_submits(client: TestClient, monkeypatch):
    _seed_chain("j-ok")
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit_rerun",
                        lambda job_id, pass_index: captured.update(job_id=job_id, idx=pass_index) or job_id)
    resp = client.post("/api/chain/rerun", json={"job_id": "j-ok", "pass_index": 1})
    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"] == "j-ok"
    assert data["stream_url"] == "/api/events/j-ok"
    assert captured == {"job_id": "j-ok", "idx": 1}


def test_rerun_updates_cached_title(client: TestClient, monkeypatch):
    """用户点过「换标题」→ 重跑必须带上新标题。

    链状态是起飞时缓存的（title=None / 旧标题），而标题守卫拿它去「纠正」
    重跑出来的标题 —— 不透传的话新标题会被钉回旧的，界面显示新的、导出是
    旧的。这是守卫上线后新出现的坑。
    """
    _seed_chain("j-title")
    monkeypatch.setattr(generate_service, "submit_rerun", lambda job_id, idx: job_id)

    resp = client.post("/api/chain/rerun",
                       json={"job_id": "j-title", "pass_index": 0, "title": "换过的新标题"})
    assert resp.status_code == 202
    assert chain_service.get_state("j-title").title == "换过的新标题"

    # 空白 / 不传 = 没改过，保留缓存值（老客户端零回归）
    for body in ({"job_id": "j-title", "pass_index": 0, "title": "   "},
                 {"job_id": "j-title", "pass_index": 0}):
        assert client.post("/api/chain/rerun", json=body).status_code == 202
        assert chain_service.get_state("j-title").title == "换过的新标题"


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
