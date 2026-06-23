from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.brand_memory.whitelist import build_fact_whitelist, normalize_numbers


def test_normalize_handles_wan_and_decimal():
    assert normalize_numbers("12万转，35kPa，1.2L") == {120000.0, 35.0, 1.2}


def test_whitelist_unions_specs_and_injected_text():
    mem = BrandModelMemory(
        brand="CEWEY", model="DS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE", "FCC"],
    )
    wl = build_fact_whitelist(mem, injected_texts=["实测气流 1700L/min，22项黑科技"])
    assert 220.0 in wl.numbers          # 来自 specs
    assert 1700.0 in wl.numbers         # 来自注入话术
    assert 22.0 in wl.numbers
    assert "CE" in wl.certs


def test_out_of_whitelist_number_detected():
    mem = BrandModelMemory(brand="CEWEY", model="DS18", category="吸尘器", role="主推",
                           specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])})
    wl = build_fact_whitelist(mem, injected_texts=[])
    # 250 既不在 specs 也不在注入源 → 越界
    assert 250.0 not in wl.numbers
