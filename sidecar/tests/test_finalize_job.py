"""Task B: _finalize_job worker 直驱。

- happy：bus.finish 带 final_text + passes + document=None；
- 复用 job_id：finalize 后 chain_service.rerun(job_id, 0) 命中（链状态同 id 缓存）；
- cancel：预置取消 → bus.fail(cancelled)。
"""
from __future__ import annotations

from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, factcheck_service, skills_service


class _Seq:
    """确定性序列 client —— 每次 complete 自增，便于断言 rerun 改写。"""
    def __init__(self, start: int = 0) -> None:
        self.n = start

    def complete(self, *, system, user, temperature=None) -> str:
        self.n += 1
        return f"OUT[{self.n}]"


def _Skill(skill_id: str, *, role: str, name: str, body: str):
    return skills_service.Skill(
        id=skill_id, name=name, desc="", tone="", role=role,
        path=Path(f"{skill_id}.md"), body=body,
    )


def _wire(monkeypatch, tmp_path: Path, *, skills: dict, client):
    """Stub _finalize_job 的重依赖（含缓存 plan）。返回截获字典。"""
    chain_service.reset_for_test()
    factcheck_service.reset_for_test()

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        skill_dir=str(tmp_path / "skills"),
        brand_memory=BrandMemoryConfig(inject=False, factcheck=False),
    )
    monkeypatch.setattr(generate_service.config_service, "load", lambda: cfg)
    monkeypatch.setattr(generate_service.templates_service, "resolve_dir", lambda: tmp_path)
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")

    plan = AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)
    monkeypatch.setattr(generate_service.assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": plan, "template_id": "t", "seed": 0})())
    monkeypatch.setattr(generate_service, "scan_vault", lambda root: object())
    monkeypatch.setattr(generate_service, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(generate_service, "load_template",
                        lambda p: type("T", (), {"product": "吸尘器"})())
    monkeypatch.setattr(generate_service.skills_service, "get_skill",
                        lambda sdir, sid: skills.get(sid))

    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: client)

    finish_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "finish", lambda job_id, **d: finish_calls.update(d))
    fail_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "fail", lambda job_id, **d: fail_calls.update(d, error=d.get("error")))
    events: list = []
    monkeypatch.setattr(generate_service.bus, "publish", lambda job_id, kind, **d: events.append((kind, d)))
    return {"finish": finish_calls, "fail": fail_calls, "events": events}


def test_finalize_job_happy(tmp_path: Path, monkeypatch):
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="人设BODY")}
    cap = _wire(monkeypatch, tmp_path, skills=skills, client=_Seq())
    req = generate_service.FinalizeRequest(
        draft="用户编辑后的初稿", keyword="无线吸尘器", skill_chain=["人设"],
    )
    generate_service._finalize_job("job-fin", req)

    fin = cap["finish"]
    assert fin["document"] is None
    assert fin["final_text"] == "OUT[1]"
    assert len(fin["passes"]) == 1
    assert fin["passes"][0]["role"] == "persona"
    assert fin["draft"] == "用户编辑后的初稿"
    assert any(k == "pass" for k, _ in cap["events"])
    # 整篇润色 done 带 cost 摘要（model 未指定 → 无默认 provider → cost=None，
    # 但 token 仍汇总、currency 恒在）。证明 _finalize_job done 这条 emit 接了 cost。
    assert fin["cost"]["currency"] == "CNY"
    assert fin["cost"]["output_tokens"] >= 0


def test_finalize_job_reuses_job_id_for_rerun(tmp_path: Path, monkeypatch):
    """finalize 后链状态缓存于同 job_id → rerun 命中（证明复用 job_id 正确）。"""
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="B")}
    _wire(monkeypatch, tmp_path, skills=skills, client=_Seq())
    req = generate_service.FinalizeRequest(draft="初稿", keyword="k", skill_chain=["人设"])
    generate_service._finalize_job("job-reuse", req)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: _Seq(start=50))
    res = chain_service.rerun("job-reuse", 0)
    assert res["passes"][0]["output"] == "OUT[51]"
    assert res["final_text"] == res["passes"][-1]["output"]


def test_finalize_job_cancel(tmp_path: Path, monkeypatch):
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="B")}
    cap = _wire(monkeypatch, tmp_path, skills=skills, client=_Seq())
    with generate_service._state_lock:
        generate_service._cancelled.add("job-cancel")
    req = generate_service.FinalizeRequest(draft="初稿", keyword="k", skill_chain=["人设"])
    generate_service._finalize_job("job-cancel", req)
    assert cap["fail"].get("cancelled") is True
    assert "finish" not in cap or not cap["finish"]
