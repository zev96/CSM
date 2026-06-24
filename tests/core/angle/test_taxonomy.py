from csm_core.angle import taxonomy as t


def test_tones_three():
    assert set(t.TONES) == {"口语", "专业", "极客"}
    assert all(t.TONES[k].strip() for k in t.TONES)


def test_dimensions_have_key_and_label():
    keys = [d["key"] for d in t.SELLPOINT_DIMENSIONS]
    assert len(keys) == len(set(keys)), "维度 key 不可重复"
    assert all(d["key"] and d["label"] for d in t.SELLPOINT_DIMENSIONS)


def test_audiences_16_and_dims_valid():
    assert len(t.AUDIENCES) == 16
    valid = {d["key"] for d in t.SELLPOINT_DIMENSIONS}
    for name, prof in t.AUDIENCES.items():
        # 主推维度要么空、要么在维度表里
        assert prof["主推维度"] in valid or prof["主推维度"] == ""
        assert prof["痛点主题"] and prof["科普主题"]


def test_presets_reference_valid_facets():
    valid_dim = {d["key"] for d in t.SELLPOINT_DIMENSIONS}
    for p in t.PRESETS:
        assert p["name"]
        if p["audience"] is not None:
            assert p["audience"] in t.AUDIENCES
        if p["tone"] is not None:
            assert p["tone"] in t.TONES
        for s in p["sellpoints"]:
            assert s in valid_dim
