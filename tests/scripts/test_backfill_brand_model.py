from scripts.backfill_brand_model import derive_note_plan, build_brand_models

BM = {"CEWEY": ["CEWEYDS18"], "小米": ["米家3C"]}


def _parts(*p):
    return tuple(p)


def test_param_note_gets_brand_and_full_stem_model():
    plan = derive_note_plan(_parts("产品参数", "CEWEYDS18-产品参数.md"), "CEWEYDS18-产品参数", BM)
    assert plan.keys == {"品牌": "CEWEY", "型号": "CEWEYDS18"}
    assert plan.unparseable is None


def test_param_note_folds_alias_brand_keeps_full_stem():
    plan = derive_note_plan(_parts("产品参数", "米家3C-产品参数.md"), "米家3C-产品参数", BM)
    assert plan.keys == {"品牌": "小米", "型号": "米家3C"}


def test_test_result_note_gets_brand_and_full_stem():
    plan = derive_note_plan(
        _parts("品牌产品测试结果", "戴森V12-测试结果.md"), "戴森V12-测试结果", BM)
    assert plan.keys == {"品牌": "戴森", "型号": "戴森V12"}


def test_endorsement_note_gets_brand_only_from_folder():
    plan = derive_note_plan(
        _parts("希喂推荐内容", "品牌背书", "吸尘器-CEWEY品牌背书-品牌定位①.md"),
        "吸尘器-CEWEY品牌背书-品牌定位①", BM)
    assert plan.keys == {"品牌": "CEWEY"}


def test_script_note_gets_brand_and_applicable_models():
    plan = derive_note_plan(
        _parts("希喂推荐内容", "核心技术", "吸尘器-CEWEY核心技术-动力系统①.md"),
        "吸尘器-CEWEY核心技术-动力系统①", BM)
    assert plan.keys == {"品牌": "CEWEY", "适用型号": ["CEWEYDS18"]}


def test_non_target_note_returns_none():
    assert derive_note_plan(_parts("科普模块", "挑选攻略", "x.md"), "x", BM) is None


def test_unparseable_param_filename_flagged_not_guessed():
    plan = derive_note_plan(_parts("产品参数", "杂牌X9-产品参数.md"), "杂牌X9-产品参数", BM)
    assert plan.keys == {}
    assert "杂牌X9" in plan.unparseable


def test_build_brand_models_groups_full_stems_by_canonical(tmp_path):
    d = tmp_path / "营销资料库/产品模块/吸尘器/产品参数"
    d.mkdir(parents=True)
    for stem in ("CEWEYDS18-产品参数", "米家3C-产品参数", "米家3基站版-产品参数"):
        (d / f"{stem}.md").write_text("---\n产品: 吸尘器\n---\n体\n", encoding="utf-8")
    bm = build_brand_models(tmp_path)
    assert bm["CEWEY"] == ["CEWEYDS18"]
    assert set(bm["小米"]) == {"米家3C", "米家3基站版"}
