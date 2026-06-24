from pathlib import Path

from csm_core.config import AppConfig, BrandMemoryConfig
from csm_core.assembler.plan import AssemblyPlan
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.brand_memory.inject import ModelScope
from csm_sidecar.services import generate_service, factcheck_service


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="CEWEYDS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE"],
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


def _plan() -> AssemblyPlan:
    return AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)


def _cfg(*, factcheck: bool) -> AppConfig:
    return AppConfig(out_dir="x", brand_memory=BrandMemoryConfig(factcheck=factcheck))


def _capture_finish(monkeypatch):
    calls = {}
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: calls.update(job_id=job_id, **d))
    return calls


def test_gate_blocks_on_fabricated_number(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    calls = _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job1", final_text="吸力高达250AW。", scopes=[_scope()],
        draft="草稿：220AW。", brand_facts=None, cfg=_cfg(factcheck=True),
        plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is True
    assert calls["document"] is None
    assert calls["factcheck"]["blocked"] is True
    assert calls["factcheck"]["violations"][0]["value"] == "250AW"
    assert factcheck_service.get_pending("job1") is not None


def test_gate_passes_on_faithful_text(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    calls = _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job2", final_text="吸力220AW，通过CE认证。", scopes=[_scope()],
        draft="草稿：220AW。", brand_facts=None, cfg=_cfg(factcheck=True),
        plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is False
    assert calls == {}
    assert factcheck_service.get_pending("job2") is None


def test_gate_disabled_returns_false(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    calls = _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job3", final_text="吸力999AW。", scopes=[_scope()],
        draft="", brand_facts=None, cfg=_cfg(factcheck=False),
        plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is False and calls == {}


def test_gate_no_scopes_returns_false(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job4", final_text="吸力999AW。", scopes=[], draft="",
        brand_facts=None, cfg=_cfg(factcheck=True), plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is False
