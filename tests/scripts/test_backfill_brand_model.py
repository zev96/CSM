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


from scripts.backfill_brand_model import insert_frontmatter_keys

_LF = "---\n产品: 吸尘器\n素材类型: 产品参数\n---\n\n## 正文\n内容\n"


def test_insert_adds_before_closing_delim_preserving_lf():
    out = insert_frontmatter_keys(_LF, {"品牌": "CEWEY", "型号": "CEWEYDS18"})
    assert "\r\n" not in out
    assert out == (
        "---\n产品: 吸尘器\n素材类型: 产品参数\n"
        "品牌: CEWEY\n型号: CEWEYDS18\n"
        "---\n\n## 正文\n内容\n"
    )


def test_insert_preserves_crlf():
    crlf = _LF.replace("\n", "\r\n")
    out = insert_frontmatter_keys(crlf, {"品牌": "CEWEY"})
    assert "品牌: CEWEY\r\n---\r\n" in out
    assert "\n" not in out.replace("\r\n", "")  # 没有裸 \n


def test_insert_renders_list_as_flow_style():
    out = insert_frontmatter_keys(_LF, {"适用型号": ["CEWEYDS18"]})
    assert "适用型号: [CEWEYDS18]\n" in out


def test_insert_empty_keys_is_noop():
    assert insert_frontmatter_keys(_LF, {}) == _LF


def test_insert_without_frontmatter_block_raises():
    import pytest
    with pytest.raises(ValueError):
        insert_frontmatter_keys("没有 frontmatter 的正文\n", {"品牌": "CEWEY"})


from scripts.backfill_brand_model import process_note, NotePlan


def _make_param(tmp_path):
    p = tmp_path / "CEWEYDS18-产品参数.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n\n## 性能\n吸力 220\n",
        encoding="utf-8")
    return p


def test_process_adds_missing_keys_and_keeps_body(tmp_path):
    p = _make_param(tmp_path)
    plan = NotePlan(keys={"品牌": "CEWEY", "型号": "CEWEYDS18"})
    res = process_note(p, plan, apply=True, backup_path=None)
    assert res.status == "added"
    text = p.read_text(encoding="utf-8")
    assert "品牌: CEWEY\n" in text and "型号: CEWEYDS18\n" in text
    assert "## 性能\n吸力 220" in text  # 正文不动
    assert "素材类型: 产品参数" in text  # 既有键不动


def test_process_is_idempotent(tmp_path):
    p = _make_param(tmp_path)
    plan = NotePlan(keys={"品牌": "CEWEY", "型号": "CEWEYDS18"})
    process_note(p, plan, apply=True, backup_path=None)
    before = p.read_text(encoding="utf-8")
    res2 = process_note(p, plan, apply=True, backup_path=None)
    assert res2.status == "skip"
    assert p.read_text(encoding="utf-8") == before  # 第二次零改动


def test_process_never_overwrites_existing_key(tmp_path):
    p = tmp_path / "CEWEY DS18-测试结果.md"
    p.write_text(
        "---\n产品: 吸尘器\n型号: CEWEY DS18\n素材类型: 测试数据\n---\n正文\n",
        encoding="utf-8")
    plan = NotePlan(keys={"品牌": "CEWEY", "型号": "CEWEY DS18"})
    res = process_note(p, plan, apply=True, backup_path=None)
    assert res.status == "added"
    assert res.added == {"品牌": "CEWEY"}  # 只补 品牌
    text = p.read_text(encoding="utf-8")
    assert text.count("型号:") == 1  # 既有 型号 未被复写


def test_process_dry_run_writes_nothing(tmp_path):
    p = _make_param(tmp_path)
    before = p.read_text(encoding="utf-8")
    res = process_note(p, NotePlan(keys={"品牌": "CEWEY"}), apply=False, backup_path=None)
    assert res.status == "added"  # 报告「会改」但不落盘
    assert p.read_text(encoding="utf-8") == before


def test_process_writes_backup(tmp_path):
    p = _make_param(tmp_path)
    bak = tmp_path / "bak" / "CEWEYDS18-产品参数.md"
    process_note(p, NotePlan(keys={"品牌": "CEWEY"}), apply=True, backup_path=bak)
    assert bak.exists()
    assert "品牌:" not in bak.read_text(encoding="utf-8")  # 备份是改前原文
