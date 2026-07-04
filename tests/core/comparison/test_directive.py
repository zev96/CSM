from csm_core.comparison.directive import build_comparison_directive


def test_directive_names_primary_and_core_constraints():
    d = build_comparison_directive(primary_label="CEWEY CEWEYDS18", tone=None)
    assert "横评" in d
    assert "CEWEY CEWEYDS18" in d           # 结论突出主推
    assert "不得使用贬损" in d
    assert "照抄" in d                       # 参数不得改写


def test_directive_merges_tone():
    d = build_comparison_directive(primary_label="CEWEY CEWEYDS18", tone="口语")
    assert "口语" in d


def test_directive_without_primary_omits_primary_clause():
    d = build_comparison_directive(primary_label=None, tone=None)
    assert "横评" in d
    # 无主推时不硬塞「突出 None」
    assert "None" not in d
