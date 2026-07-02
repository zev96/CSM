"""Unit B2.1: generate_service 接角度全链（采样/注入卖点/角度指令/标题/白名单）。

单元级，全程 mock：截获 assemble_plan / render_brand_facts / build_prompt /
build_whitelist 的入参，验证 GenerateRequest.title/angle 被正确分发到各层。
不跑真实 vault / LLM。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_core.angle import Angle
from csm_core.assembler.plan import AssemblyPlan
from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, factcheck_service


def test_request_accepts_title_and_angle():
    a = Angle(audience="铲屎官", sellpoints=["防缠绕技术"], tone="口语")
    req = generate_service.GenerateRequest(
        keyword="无线吸尘器", template_id="t", title="标题啊", angle=a,
    )
    assert req.title == "标题啊"
    assert req.angle == a
    # 默认零回归：不传时 None
    bare = generate_service.GenerateRequest(keyword="k", template_id="t")
    assert bare.title is None and bare.angle is None


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="CEWEYDS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE"],
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


class _StubClient:
    def complete(self, *, system: str, user: str) -> str:  # noqa: D401
        return "成稿：吸力220AW。"


def _wire_full_chain(monkeypatch, tmp_path: Path, *, inject: bool, factcheck: bool):
    """把 _run_job 依赖全部 stub 掉，返回截获到的入参字典。"""
    captured: dict = {}

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        brand_memory=BrandMemoryConfig(inject=inject, factcheck=factcheck),
    )
    monkeypatch.setattr(generate_service.config_service, "load", lambda: cfg)
    monkeypatch.setattr(
        generate_service.templates_service, "resolve_dir", lambda: tmp_path)
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(generate_service.vault_service, "get", lambda root: object())
    monkeypatch.setattr(generate_service, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(generate_service, "load_template",
                        lambda p: type("T", (), {"product": "吸尘器"})())

    def fake_assemble_plan(**kwargs):
        captured["assemble_kwargs"] = kwargs
        return AssemblyPlan(keyword=kwargs["keyword"], template_id="t", seed=0)

    monkeypatch.setattr(generate_service, "assemble_plan", fake_assemble_plan)
    monkeypatch.setattr(generate_service.assembler_service, "cache_plan",
                        lambda *a, **k: None)
    monkeypatch.setattr(generate_service, "compose_draft", lambda plan: "毛坯文")

    monkeypatch.setattr(generate_service, "resolve_scopes",
                        lambda *a, **k: [_scope()])

    def fake_render_brand_facts(scopes, **kwargs):
        captured["render_kwargs"] = kwargs
        return "品牌事实块"

    monkeypatch.setattr(generate_service, "render_brand_facts", fake_render_brand_facts)
    # Phase 2b：LLM 调用从 generate_service 单次 build_prompt+complete 迁入
    # chain_service.run_chain（step0=build_prompt）。client + build_prompt 现在
    # 由 chain_service 调用，故 patch 落在 chain_service 上。
    monkeypatch.setattr(chain_service.llm_factory, "build_client",
                        lambda **k: _StubClient())

    def fake_build_prompt(inputs):
        captured["prompt_inputs"] = inputs
        return ("sys", "user")

    monkeypatch.setattr(chain_service, "build_prompt", fake_build_prompt)

    def fake_build_whitelist(scopes, *, source_texts):
        captured["whitelist_sources"] = source_texts
        return type("WL", (), {"numbers": set(), "certs": set()})()

    monkeypatch.setattr(generate_service, "build_whitelist", fake_build_whitelist)
    monkeypatch.setattr(generate_service, "check_facts",
                        lambda *a, **k: type("R", (), {"ok": True})())

    captured_export: dict = {}
    monkeypatch.setattr(generate_service, "export_article",
                        lambda **k: {"document": "d", "format": "markdown", "title": "ti"})
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: captured_export.update(d))
    monkeypatch.setattr(generate_service.bus, "publish", lambda *a, **k: None)
    captured["export"] = captured_export
    return captured


def test_full_chain_receives_angle(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    cap = _wire_full_chain(monkeypatch, tmp_path, inject=True, factcheck=True)
    a = Angle(audience="铲屎官", sellpoints=["防缠绕技术"], tone="口语")
    req = generate_service.GenerateRequest(
        keyword="无线吸尘器", template_id="t",
        title="无线吸尘器哪款好？", angle=a,
    )
    generate_service._run_job("job-ang", req)

    # assemble_plan 收到 angle
    assert cap["assemble_kwargs"]["angle"] == a
    # render_brand_facts 收到 effective_sellpoints
    assert cap["render_kwargs"]["sellpoints"] == ["防缠绕技术"]
    # build_prompt 收到 title + 非空 angle_directive
    pi = cap["prompt_inputs"]
    assert pi.title == "无线吸尘器哪款好？"
    assert pi.angle_directive is not None and "铲屎官" in pi.angle_directive
    # factcheck 白名单源含 title
    assert "无线吸尘器哪款好？" in cap["whitelist_sources"]


def test_no_angle_no_title_zero_regression(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    cap = _wire_full_chain(monkeypatch, tmp_path, inject=True, factcheck=True)
    req = generate_service.GenerateRequest(keyword="kw", template_id="t")
    generate_service._run_job("job-bare", req)

    assert cap["assemble_kwargs"]["angle"] is None
    # 没卖点 → 空列表（render 仍被调用因为 inject=True 且有 scope）
    assert cap["render_kwargs"]["sellpoints"] == []
    pi = cap["prompt_inputs"]
    assert pi.title is None
    assert pi.angle_directive is None
    # 白名单源 = draft + brand_facts（无 title）
    assert "毛坯文" in cap["whitelist_sources"]


def test_factcheck_sources_include_title_param(tmp_path: Path, monkeypatch):
    """_maybe_block_for_factcheck 直接接 title 形参并纳入白名单源。"""
    factcheck_service.reset_for_test()
    captured: dict = {}
    monkeypatch.setattr(
        generate_service, "build_whitelist",
        lambda scopes, *, source_texts: captured.update(sources=source_texts)
        or type("WL", (), {"numbers": set(), "certs": set()})())
    monkeypatch.setattr(generate_service, "check_facts",
                        lambda *a, **k: type("R", (), {"ok": True})())
    cfg = AppConfig(out_dir="x", brand_memory=BrandMemoryConfig(factcheck=True))
    generate_service._maybe_block_for_factcheck(
        "jt", final_text="文本", scopes=[_scope()], draft="草稿",
        brand_facts="事实", title="我的标题", cfg=cfg,
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0), out_dir=tmp_path,
    )
    assert captured["sources"] == ["草稿", "我的标题", "事实"]
