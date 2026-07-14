from csm_core.brand_memory.identity import canonical_brand, note_identity, parse_brand_model

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


def test_note_identity_frontmatter_first():
    # frontmatter 品牌/型号 优先于文件名解析(未知品牌 DARZ 不在别名表也能命中)
    fm = {"品牌": "DARZ", "型号": "DARZD9"}
    assert note_identity("DARZD9-产品参数", fm, ALIASES) == ("DARZ", "DARZD9")


def test_note_identity_frontmatter_brand_folds_alias():
    fm = {"品牌": "米家", "型号": "米家3C"}
    assert note_identity("米家3C-产品参数", fm, ALIASES) == ("小米", "米家3C")


def test_note_identity_filename_fallback():
    # 无 frontmatter → 文件名解析品牌 + full-stem 型号(与 registry 现行为一致)
    assert note_identity("CEWEYDS18-产品参数", {}, ALIASES) == ("CEWEY", "CEWEYDS18")


def test_note_identity_partial_frontmatter():
    # 只有 型号 没有 品牌 → 品牌走文件名解析
    fm = {"型号": "CEWEYDS18"}
    assert note_identity("CEWEYDS18-产品参数", fm, ALIASES) == ("CEWEY", "CEWEYDS18")


def test_note_identity_unresolvable_returns_none():
    # 品牌既不在 frontmatter 也解析不出 → None(registry 的 skip 行为)
    assert note_identity("某杂牌X9-产品参数", {}, ALIASES) is None
    assert note_identity("某杂牌X9-产品参数", None, ALIASES) is None
