"""Unit B1: generate_service 接 skill 链跑（run_chain 替换单次 complete）。

单元级，全程 mock（不跑真实 vault / LLM）。断言：
- 传 skill_chain → run_chain 收到对应 steps（按 id 顺序、role/name/body 来自 skill）；
- done 带 passes；
- 单 skill_id（无 chain）→ 1 pass、step0 的 PromptInputs 与今天一致、final 同今天；
- 被事实核对拦下的 done 也带 passes；
- 单 skill_id 失效（chain 为空且 skill_id 给了但找不到）→ 仍 RAISE（零回归）。
"""
from __future__ import annotations

from pathlib import Path

from csm_core.angle import Angle
from csm_core.assembler.plan import AssemblyPlan
from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, factcheck_service, skills_service


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="CEWEYDS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE"],
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


def _Skill(skill_id: str, *, role: str, name: str, body: str):
    return skills_service.Skill(
        id=skill_id, name=name, desc="", tone="", role=role,
        path=Path(f"{skill_id}.md"), body=body,
    )


class _StubClient:
    """Returns a deterministic final + records calls for prompt assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "成稿：吸力220AW。"


def _wire(monkeypatch, tmp_path: Path, *, inject: bool, factcheck: bool, skills: dict | None = None):
    """Stub _run_job 的所有重依赖，返回截获字典。skills 是 {id: Skill} 表。"""
    captured: dict = {}
    chain_service.reset_for_test()
    skills = skills or {}

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        skill_dir=str(tmp_path / "skills"),
        brand_memory=BrandMemoryConfig(inject=inject, factcheck=factcheck),
    )
    monkeypatch.setattr(generate_service.config_service, "load", lambda: cfg)
    monkeypatch.setattr(generate_service.templates_service, "resolve_dir", lambda: tmp_path)
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(generate_service.vault_service, "get", lambda root: object())
    monkeypatch.setattr(generate_service, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(generate_service, "load_template",
                        lambda p: type("T", (), {"product": "吸尘器"})())

    monkeypatch.setattr(generate_service, "assemble_plan",
                        lambda **k: AssemblyPlan(keyword=k["keyword"], template_id="t", seed=0))
    monkeypatch.setattr(generate_service.assembler_service, "cache_plan", lambda *a, **k: None)
    monkeypatch.setattr(generate_service, "compose_draft", lambda plan: "毛坯文")

    monkeypatch.setattr(generate_service, "resolve_scopes", lambda *a, **k: [_scope()])
    monkeypatch.setattr(generate_service, "render_brand_facts", lambda scopes, **k: "品牌事实块")

    # skills_service.get_skill：从表里取（None = 找不到）
    monkeypatch.setattr(generate_service.skills_service, "get_skill",
                        lambda sdir, sid: skills.get(sid))

    # 真实 chain_service.run_chain，但 client 走 stub（通过 build_client 注入）
    stub = _StubClient()
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: stub)
    captured["client"] = stub

    # 截获 run_chain 入参（包一层，仍调真实实现）
    real_run_chain = chain_service.run_chain

    def spy_run_chain(job_id, steps, **kwargs):
        captured["run_chain_steps"] = steps
        captured["run_chain_kwargs"] = kwargs
        return real_run_chain(job_id, steps, **kwargs)

    monkeypatch.setattr(generate_service.chain_service, "run_chain", spy_run_chain)

    monkeypatch.setattr(generate_service, "build_whitelist",
                        lambda scopes, *, source_texts: type("WL", (), {"numbers": set(), "certs": set()})())
    monkeypatch.setattr(generate_service, "check_facts",
                        lambda *a, **k: type("R", (), {"ok": True})())

    monkeypatch.setattr(generate_service, "export_article",
                        lambda **k: {"document": "d", "format": "markdown", "title": "ti"})
    finish_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: finish_calls.update(d))
    events: list = []
    monkeypatch.setattr(generate_service.bus, "publish",
                        lambda job_id, kind, **d: events.append((kind, d)))
    captured["finish"] = finish_calls
    captured["events"] = events
    return captured


def test_skill_chain_resolves_to_ordered_steps(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    skills = {
        "人设": _Skill("人设", role="persona", name="克制理性", body="人设BODY"),
        "去味": _Skill("去味", role="humanize", name="去AI味", body="去味BODY"),
    }
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=False, skills=skills)
    req = generate_service.GenerateRequest(
        keyword="无线吸尘器", template_id="t", skill_chain=["人设", "去味"],
    )
    generate_service._run_job("job-chain", req)

    steps = cap["run_chain_steps"]
    assert [s.skill_id for s in steps] == ["人设", "去味"]
    assert [s.role for s in steps] == ["persona", "humanize"]
    assert [s.name for s in steps] == ["克制理性", "去AI味"]
    assert [s.body for s in steps] == ["人设BODY", "去味BODY"]
    # done 带 passes（2 步 → 2 passes）
    passes = cap["finish"]["passes"]
    assert len(passes) == 2
    assert passes[0]["role"] == "persona" and passes[1]["role"] == "humanize"


def test_single_skill_id_zero_regression(tmp_path: Path, monkeypatch):
    """单 skill_id（无 chain）→ 1 pass、step0 PromptInputs 与今天一致、final 同今天。"""
    factcheck_service.reset_for_test()
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="人设BODY")}
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=False, skills=skills)
    a = Angle(audience="铲屎官", sellpoints=["防缠绕技术"], tone="口语")
    req = generate_service.GenerateRequest(
        keyword="无线吸尘器", template_id="t", skill_id="人设",
        title="无线吸尘器哪款好？", angle=a,
    )
    generate_service._run_job("job-single", req)

    # 单步链
    steps = cap["run_chain_steps"]
    assert len(steps) == 1 and steps[0].skill_id == "人设"
    # run_chain 收到的 draft/keyword/title/angle_directive/brand_facts 与今天 build_prompt 入参一致
    kw = cap["run_chain_kwargs"]
    assert kw["draft"] == "毛坯文"
    assert kw["keyword"] == "无线吸尘器"
    assert kw["title"] == "无线吸尘器哪款好？"
    assert kw["angle_directive"] is not None and "铲屎官" in kw["angle_directive"]
    assert kw["brand_facts"] == "品牌事实块"  # inject=True 时注入
    # step0 实际喂给 client 的 system/user == build_prompt(同样入参)
    from csm_core.llm.prompts import build_prompt, PromptInputs
    from csm_core.angle import render_angle_directive
    exp_sys, exp_user = build_prompt(PromptInputs(
        user_skill_prompt="人设BODY", keyword="无线吸尘器", draft="毛坯文",
        brand_facts="品牌事实块", title="无线吸尘器哪款好？",
        angle_directive=render_angle_directive(a)))
    assert cap["client"].calls[0] == (exp_sys, exp_user)
    # final 同今天（stub 的固定输出）
    assert cap["finish"]["final_text"] == "成稿：吸力220AW。"
    assert len(cap["finish"]["passes"]) == 1
    # pass SSE 事件发出
    assert any(k == "pass" for k, _ in cap["events"])


def test_inject_off_no_brand_facts_into_step0(tmp_path: Path, monkeypatch):
    """inject=False → run_chain 收到 brand_facts=None（与今天一致）。"""
    factcheck_service.reset_for_test()
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="B")}
    cap = _wire(monkeypatch, tmp_path, inject=False, factcheck=False, skills=skills)
    req = generate_service.GenerateRequest(keyword="k", template_id="t", skill_id="人设")
    generate_service._run_job("job-noinject", req)
    assert cap["run_chain_kwargs"]["brand_facts"] is None


def test_missing_single_skill_id_raises(tmp_path: Path, monkeypatch):
    """单 skill_id 给了但找不到 → 仍 RAISE（不静默成空链）；以 error 事件收尾。"""
    factcheck_service.reset_for_test()
    cap = _wire(monkeypatch, tmp_path, inject=False, factcheck=False, skills={})
    fail_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "fail",
                        lambda job_id, **d: fail_calls.update(d))
    req = generate_service.GenerateRequest(keyword="k", template_id="t", skill_id="不存在")
    generate_service._run_job("job-missing", req)
    # run_chain 不应被调用（在解析阶段就炸）
    assert "run_chain_steps" not in cap
    assert "skill not found" in fail_calls.get("error", "")


def test_blocked_done_carries_passes(tmp_path: Path, monkeypatch):
    """事实核对拦下 → done(blocked) 也带 passes。"""
    factcheck_service.reset_for_test()
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="B")}
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=True, skills=skills)
    # check_facts 返回 not ok（一个越界）
    from csm_core.factcheck import Violation

    class _Report:
        ok = False
        violations = [Violation(kind="number", value="250AW", number=250.0,
                                sentence="句子", suggestion="建议")]

    monkeypatch.setattr(generate_service, "check_facts", lambda *a, **k: _Report())
    monkeypatch.setattr(generate_service.factcheck_service, "cache_pending", lambda *a, **k: None)

    req = generate_service.GenerateRequest(keyword="k", template_id="t", skill_id="人设")
    generate_service._run_job("job-blocked", req)

    fin = cap["finish"]
    assert fin["factcheck"]["blocked"] is True
    assert fin["document"] is None
    assert "passes" in fin and len(fin["passes"]) == 1
