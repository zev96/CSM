"""spec_fingerprint + diff_canonical —— 占位/顺序/certs 参与、scripts 不参与、稳定性。"""
from csm_core.brand_memory.fingerprint import diff_canonical, spec_fingerprint
from csm_core.brand_memory.model import BrandModelMemory, SpecValue


def _mem(specs=None, certs=None, scripts=None) -> BrandModelMemory:
    sv = {f: SpecValue(field=f, raw=raw, is_placeholder=ph)
          for f, (raw, ph) in (specs or {}).items()}
    return BrandModelMemory(
        brand="戴森", model="V12", category="吸尘器", role="主推",
        specs=sv, certs=certs or [], scripts=scripts or {},
    )


def test_placeholder_excluded():
    m1 = _mem(specs={"吸力": ("150AW", False), "噪音": ("0", True)})
    m2 = _mem(specs={"吸力": ("150AW", False), "噪音": ("未说明", True)})
    assert spec_fingerprint(m1)[0] == spec_fingerprint(m2)[0]  # 占位值差异不影响指纹


def test_order_independent():
    m1 = _mem(specs={"吸力": ("150AW", False), "续航": ("60min", False)})
    m2 = _mem(specs={"续航": ("60min", False), "吸力": ("150AW", False)})
    assert spec_fingerprint(m1)[0] == spec_fingerprint(m2)[0]


def test_cert_participates():
    assert spec_fingerprint(_mem(certs=["3C"]))[0] != spec_fingerprint(_mem(certs=["3C", "CE"]))[0]


def test_scripts_not_participate():
    m1 = _mem(specs={"吸力": ("150AW", False)}, scripts={"卖点": ["强劲"]})
    m2 = _mem(specs={"吸力": ("150AW", False)}, scripts={"卖点": ["超强劲吸力，一遍净"]})
    assert spec_fingerprint(m1)[0] == spec_fingerprint(m2)[0]


def test_spec_change_shifts_fingerprint():
    assert spec_fingerprint(_mem(specs={"吸力": ("150AW", False)}))[0] \
        != spec_fingerprint(_mem(specs={"吸力": ("230AW", False)}))[0]


def test_stable_across_calls():
    m = _mem(specs={"吸力": ("150AW", False)}, certs=["3C"])
    assert spec_fingerprint(m) == spec_fingerprint(m)


def test_diff_canonical_spec_change():
    _, c1 = spec_fingerprint(_mem(specs={"吸力": ("150AW", False)}))
    _, c2 = spec_fingerprint(_mem(specs={"吸力": ("230AW", False)}))
    assert diff_canonical(c1, c2) == [{"field": "吸力", "old": "150AW", "new": "230AW"}]


def test_diff_canonical_add_and_remove_spec():
    _, c1 = spec_fingerprint(_mem(specs={"吸力": ("150AW", False)}))
    _, c2 = spec_fingerprint(_mem(specs={"续航": ("60min", False)}))
    d = diff_canonical(c1, c2)
    assert {"field": "吸力", "old": "150AW", "new": None} in d
    assert {"field": "续航", "old": None, "new": "60min"} in d


def test_diff_canonical_cert_change():
    _, c1 = spec_fingerprint(_mem(certs=[]))
    _, c2 = spec_fingerprint(_mem(certs=["CE"]))
    assert {"field": "认证", "old": None, "new": "CE"} in diff_canonical(c1, c2)


def test_diff_canonical_first_build_empty():
    _, c2 = spec_fingerprint(_mem(specs={"吸力": ("150AW", False)}))
    assert diff_canonical(None, c2) == []
    assert diff_canonical("", c2) == []
    assert diff_canonical("not json", c2) == []


def test_diff_canonical_non_dict_old_degrades():
    # 合法 JSON 但非对象（数组/标量）→ 视作首建返回 []，不崩（对抗审查回归）。
    _, c2 = spec_fingerprint(_mem(specs={"吸力": ("150AW", False)}))
    assert diff_canonical("[1,2,3]", c2) == []
    assert diff_canonical("123", c2) == []
    assert diff_canonical('"hi"', c2) == []
    assert diff_canonical("true", c2) == []
