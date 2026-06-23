from csm_core.brand_memory.model import SpecValue, BrandModelMemory


def test_specvalue_defaults():
    sv = SpecValue(field="吸力(AW)", raw="220", numbers=[220.0], unit="AW")
    assert sv.is_approx is False
    assert sv.numbers == [220.0]


def test_memory_minimal():
    m = BrandModelMemory(brand="CEWEY", model="DS18", category="吸尘器", role="主推")
    assert m.specs == {} and m.scripts == {} and m.role == "主推"
