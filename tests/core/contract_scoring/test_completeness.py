from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.brand_memory.inject import ModelScope
from csm_core.factcheck.completeness import CompletenessReport, check_completeness


def _scope(role: str, numbers: dict[str, list[float]], certs: list[str] = []) -> ModelScope:
    specs = {
        k: SpecValue(field=k, raw="x", numbers=v, unit="", is_approx=False, is_placeholder=False)
        for k, v in numbers.items()
    }
    mem = BrandModelMemory(
        brand="CEWEY", model="DS18", category="吸尘器", role=role,
        specs=specs, certs=certs)
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role=role, memory=mem)


MAIN = _scope("主推", {"吸力": [250.0], "转速": [120000.0]}, certs=["CCC"])
RIVAL = _scope("竞品", {"吸力": [230.0]})


def test_missing_number_detected():
    draft = "主推吸力 250AW，转速 12万转。竞品 230AW。"
    final = "主推转速 12万转。"        # 删了 250AW
    rep = check_completeness(draft, final, [MAIN, RIVAL])
    assert rep.checked is True
    assert [m.token for m in rep.missing] == ["250AW"]
    assert rep.missing[0].value == 250.0
    assert "250AW" in rep.missing[0].sentence


def test_wan_symmetry():
    draft = "转速 12万转。"
    final = "转速 120000转。"          # 万-展开等价，不算缺失
    rep = check_completeness(draft, final, [MAIN])
    assert rep.missing == []


def test_rival_deletion_not_missing():
    draft = "主推 250AW；竞品 230AW。"
    final = "主推 250AW。"             # 竞品被删——激进契约允许
    rep = check_completeness(draft, final, [MAIN, RIVAL])
    assert rep.missing == []


def test_cert_missing():
    draft = "已通过 CCC 认证，吸力 250AW。"
    final = "吸力 250AW。"
    rep = check_completeness(draft, final, [MAIN])
    assert [m.token for m in rep.missing] == ["CCC"]
    assert rep.missing[0].kind == "cert" and rep.missing[0].value is None


def test_no_primary_scope_unchecked():
    rep = check_completeness("250AW", "", [RIVAL])
    assert rep.checked is False and rep.missing == []


def test_draft_number_not_in_specs_ignored():
    draft = "赠品价值 99元，吸力 250AW。"   # 99元 非主推 spec
    final = "吸力 250AW。"
    rep = check_completeness(draft, final, [MAIN])
    assert rep.missing == []
