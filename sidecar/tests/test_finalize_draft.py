"""Task A: finalize_draft 抽取 —— 注入+链+事实核对的共享段。

直接测 finalize_draft（与 _run_job 解耦）：
- 干净路径返回 blocked=False + final_text + passes；
- inject=False → run_chain 收到 brand_facts=None；
- 事实核对拦下 → blocked=True 且 bus.finish 带 violations + passes。
_run_job 的零回归由现存 test_generate_chain.py 保证（不在此重复）。
"""
from __future__ import annotations

from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan
from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, factcheck_service


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="CEWEYDS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE"],
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "成稿：吸力220AW。"


def _wire(monkeypatch, tmp_path: Path, *, inject: bool, factcheck: bool):
    """Stub finalize_draft 的重依赖，返回截获字典 + 一个现成 cfg。"""
    captured: dict = {}
    chain_service.reset_for_test()
    factcheck_service.reset_for_test()

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        skill_dir=str(tmp_path / "skills"),
        brand_memory=BrandMemoryConfig(inject=inject, factcheck=factcheck),
    )
    monkeypatch.setattr(generate_service, "resolve_scopes", lambda *a, **k: [_scope()])
    monkeypatch.setattr(generate_service, "render_brand_facts", lambda scopes, **k: "品牌事实块")

    stub = _StubClient()
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: stub)
    captured["client"] = stub

    real_run_chain = chain_service.run_chain

    def spy_run_chain(job_id, steps, **kwargs):
        captured["run_chain_kwargs"] = kwargs
        return real_run_chain(job_id, steps, **kwargs)

    monkeypatch.setattr(generate_service.chain_service, "run_chain", spy_run_chain)

    monkeypatch.setattr(generate_service, "build_whitelist",
                        lambda scopes, *, source_texts: type("WL", (), {"numbers": set(), "certs": set()})())
    monkeypatch.setattr(generate_service, "check_facts",
                        lambda *a, **k: type("R", (), {"ok": True})())

    finish_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: finish_calls.update(d))
    events: list = []
    monkeypatch.setattr(generate_service.bus, "publish",
                        lambda job_id, kind, **d: events.append((kind, d)))
    captured["finish"] = finish_calls
    captured["events"] = events
    captured["cfg"] = cfg
    return captured


def _steps():
    return [chain_service.ChainStepInput(skill_id="人设", role="persona", name="克制理性", body="人设BODY")]


def test_finalize_draft_clean_returns_outcome(tmp_path: Path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=False)
    outcome = generate_service.finalize_draft(
        "job-clean",
        chain_steps=_steps(), draft="毛坯文",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="无线吸尘器", title=None, angle=None,
        provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None,
        on_pass=lambda p: cap["events"].append(("pass", p.to_dict())),
        stage_index=0, stage_total=1,
        contract_mode="conservative",
    )
    assert outcome.blocked is False
    assert outcome.final_text == "成稿：吸力220AW。"
    assert len(outcome.passes) == 1
    assert cap["run_chain_kwargs"]["brand_facts"] == "品牌事实块"
    assert ("stage", {"stage": "skill 链润色", "index": 0, "total": 1}) in cap["events"]


def test_finalize_draft_inject_off_no_brand_facts(tmp_path: Path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=False, factcheck=False)
    generate_service.finalize_draft(
        "job-noinject",
        chain_steps=_steps(), draft="毛坯文",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="k", title=None, angle=None, provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=4, stage_total=6,
        contract_mode="conservative",
    )
    assert cap["run_chain_kwargs"]["brand_facts"] is None


def test_finalize_draft_blocked_carries_passes(tmp_path: Path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=True)
    from csm_core.factcheck import Violation

    class _Report:
        ok = False
        violations = [Violation(kind="number", value="250AW", number=250.0,
                                sentence="句子", suggestion="建议")]

    monkeypatch.setattr(generate_service, "check_facts", lambda *a, **k: _Report())
    monkeypatch.setattr(generate_service.factcheck_service, "cache_pending", lambda *a, **k: None)

    outcome = generate_service.finalize_draft(
        "job-blocked",
        chain_steps=_steps(), draft="毛坯文",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="k", title=None, angle=None, provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=0, stage_total=1,
        contract_mode="conservative",
    )
    assert outcome.blocked is True
    fin = cap["finish"]
    assert fin["factcheck"]["blocked"] is True
    assert fin["document"] is None
    assert len(fin["passes"]) == 1
    # 被事实核对拦下的 blocked done 也带 cost（成本已花，带上更准）；
    # outcome 与 blocked done 共用同一份 cost。
    assert outcome.cost["currency"] == "CNY"
    assert fin["cost"]["currency"] == "CNY"


class _DropStubClient:
    """成稿掉了初稿里的主推关键数字（220AW）—— 模拟激进契约取舍删减。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "成稿：清洁力强劲，体验出色。"


def test_finalize_draft_aggressive_completeness_missing(tmp_path: Path, monkeypatch):
    """激进契约 + 成稿丢了主推 220AW → outcome.completeness 非空 missing。"""
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=False)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: _DropStubClient())
    outcome = generate_service.finalize_draft(
        "job-aggressive-missing",
        chain_steps=_steps(), draft="主推吸力220AW，效果拔群。",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="无线吸尘器", title=None, angle=None,
        provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=0, stage_total=1,
        contract_mode="aggressive",
    )
    assert outcome.blocked is False
    assert outcome.completeness is not None
    assert outcome.completeness["checked"] is True
    assert [m["token"] for m in outcome.completeness["missing"]] == ["220AW"]


def test_finalize_draft_conservative_completeness_none(tmp_path: Path, monkeypatch):
    """保守契约（默认）→ 不核完整性，outcome.completeness is None。"""
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=False)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: _DropStubClient())
    outcome = generate_service.finalize_draft(
        "job-conservative-nocheck",
        chain_steps=_steps(), draft="主推吸力220AW，效果拔群。",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="无线吸尘器", title=None, angle=None,
        provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=0, stage_total=1,
        contract_mode="conservative",
    )
    assert outcome.blocked is False
    assert outcome.completeness is None
