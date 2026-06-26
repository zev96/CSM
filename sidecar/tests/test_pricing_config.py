"""Part 1 Unit B: AppConfig.pricing 字段 + done 带 cost。"""
from __future__ import annotations

from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, skills_service


def test_pricing_field_default_empty():
    assert AppConfig().pricing == {}


def test_pricing_roundtrip():
    cfg = AppConfig.model_validate({"pricing": {"deepseek-chat": {"input": 1.5, "output": 3.0}}})
    assert cfg.pricing["deepseek-chat"]["input"] == 1.5


def test_pricing_unknown_key_tolerated():
    cfg = AppConfig.model_validate({"user_name": "x"})
    assert cfg.pricing == {}


# ── generate done 带 cost ──────────────────────────────────────────────────
# sidecar/tests 无 __init__，不能跨文件 import test_generate_chain 的 _wire，
# 故内联一份精简装配（仿 test_generate_chain._wire），stub 掉 _run_job 全部重依赖。

def _Skill(skill_id: str, *, role: str, name: str, body: str):
    return skills_service.Skill(
        id=skill_id, name=name, desc="", tone="", role=role,
        path=Path(f"{skill_id}.md"), body=body,
    )


class _StubClient:
    """确定性 final，供成本估算有非零 output tokens。"""

    def complete(self, *, system: str, user: str) -> str:
        return "成稿：吸力220AW。"


def _wire(monkeypatch, tmp_path: Path, *, inject: bool, factcheck: bool, skills: dict | None = None):
    """Stub _run_job 的重依赖，cfg.pricing={}（用默认价），返回截获字典。"""
    captured: dict = {}
    chain_service.reset_for_test()
    skills = skills or {}

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        skill_dir=str(tmp_path / "skills"),
        brand_memory=BrandMemoryConfig(inject=inject, factcheck=factcheck),
        pricing={},
    )
    monkeypatch.setattr(generate_service.config_service, "load", lambda: cfg)
    monkeypatch.setattr(generate_service.templates_service, "resolve_dir", lambda: tmp_path)
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(generate_service, "scan_vault", lambda root: object())
    monkeypatch.setattr(generate_service, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(generate_service, "load_template",
                        lambda p: type("T", (), {"product": "吸尘器"})())

    monkeypatch.setattr(generate_service, "assemble_plan",
                        lambda **k: AssemblyPlan(keyword=k["keyword"], template_id="t", seed=0))
    monkeypatch.setattr(generate_service.assembler_service, "cache_plan", lambda *a, **k: None)
    monkeypatch.setattr(generate_service, "compose_draft", lambda plan: "毛坯文")

    monkeypatch.setattr(generate_service, "resolve_scopes", lambda *a, **k: [])
    monkeypatch.setattr(generate_service, "render_brand_facts", lambda scopes, **k: "品牌事实块")

    monkeypatch.setattr(generate_service.skills_service, "get_skill",
                        lambda sdir, sid: skills.get(sid))

    stub = _StubClient()
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: stub)

    monkeypatch.setattr(generate_service, "build_whitelist",
                        lambda scopes, *, source_texts: type("WL", (), {"numbers": set(), "certs": set()})())
    monkeypatch.setattr(generate_service, "check_facts",
                        lambda *a, **k: type("R", (), {"ok": True})())

    monkeypatch.setattr(generate_service, "export_article",
                        lambda **k: {"document": "d", "format": "markdown", "title": "ti"})
    finish_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: finish_calls.update(d))
    monkeypatch.setattr(generate_service.bus, "publish",
                        lambda job_id, kind, **d: None)
    captured["finish"] = finish_calls
    return captured


def test_generate_done_carries_cost(tmp_path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=False, factcheck=False,
                skills={"人设": _Skill("人设", role="persona", name="人设", body="B")})
    req = generate_service.GenerateRequest(
        keyword="无线吸尘器", template_id="t", skill_id="人设", model="deepseek-chat")
    generate_service._run_job("job-cost", req)
    cost = cap["finish"]["cost"]
    assert cost["currency"] == "CNY" and cost["cost"] is not None  # deepseek-chat 有默认价
    assert cost["input_tokens"] >= 0
