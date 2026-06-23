from csm_core.brand_memory.identity import canonical_brand, parse_brand_model

ALIASES = {
    "CEWEY": ["CEWEY", "希喂"],
    "小米": ["小米", "米家"],
    "戴森": ["戴森"],
    "友望": ["友望"],
    "追觅": ["追觅"],
}


def test_canonical_brand_folds_alias():
    assert canonical_brand("米家", ALIASES) == "小米"
    assert canonical_brand("希喂", ALIASES) == "CEWEY"
    assert canonical_brand("未知", ALIASES) == "未知"


def test_parse_brand_model_strips_suffix_and_brand():
    assert parse_brand_model("CEWEYDS18-产品参数", ALIASES) == ("CEWEY", "DS18")
    assert parse_brand_model("戴森V12-产品参数", ALIASES) == ("戴森", "V12")
    assert parse_brand_model("米家3C-产品参数", ALIASES) == ("小米", "3C")
    assert parse_brand_model("友望大橘Ultra-产品参数", ALIASES) == ("友望", "大橘Ultra")


def test_parse_brand_model_unparseable_returns_none():
    assert parse_brand_model("某杂牌X9-产品参数", ALIASES) is None


def test_parse_brand_model_default_aliases_and_test_suffix():
    # 不传 aliases → 用生产默认 BRAND_ALIASES；石头 不在本文件局部 ALIASES 里，
    # 命中即证明默认表已接好。同时覆盖 -测试结果 后缀的剥离。
    assert parse_brand_model("石头G20-测试结果") == ("石头", "G20")
