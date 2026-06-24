from pathlib import Path

import pytest

from csm_core.assembler.plan import AssemblyPlan
from csm_sidecar.services import factcheck_service


def _plan() -> AssemblyPlan:
    return AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)


def _seed(job_id: str, out_dir: Path) -> None:
    factcheck_service.cache_pending(
        job_id, plan=_plan(), out_dir=out_dir, keyword="无线吸尘器",
        fmt="markdown", allowed_numbers={220.0}, allowed_certs={"CE"},
    )


def test_resolve_exports_when_clean(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j1", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j1", final_text="吸力220AW，CE认证。", released_numbers=[], released_certs=[])
    assert res["ok"] is True
    assert Path(res["document"]).exists()
    assert factcheck_service.get_pending("j1") is None


def test_resolve_still_blocked_when_violation_remains(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j2", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j2", final_text="吸力250AW。", released_numbers=[], released_certs=[])
    assert res["ok"] is False
    assert res["violations"][0]["value"] == "250AW"
    assert factcheck_service.get_pending("j2") is not None


def test_resolve_with_released_number_passes(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j3", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j3", final_text="吸力250AW。", released_numbers=[250.0], released_certs=[])
    assert res["ok"] is True and Path(res["document"]).exists()


def test_resolve_unknown_job_raises(tmp_path: Path):
    factcheck_service.reset_for_test()
    with pytest.raises(KeyError):
        factcheck_service.resolve_and_export(
            "nope", final_text="x", released_numbers=[], released_certs=[])
