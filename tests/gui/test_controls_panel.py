from csm_gui.widgets.controls_panel import ControlsPanel


def test_controls_emits_rerun_all(qtbot, tmp_path):
    p = ControlsPanel(skill_dir=None, provider_default="mock")
    qtbot.addWidget(p)
    p.seed_input.setValue(99)
    p.brand_count_input.setValue(3)
    with qtbot.waitSignal(p.rerun_all_requested, timeout=500) as sig:
        p.rerun_all_button.click()
    seed, user_config = sig.args[0], sig.args[1]
    assert seed == 99
    assert user_config == {"brand_competitors": 3}


def test_controls_emits_polish(qtbot):
    p = ControlsPanel(skill_dir=None, provider_default="anthropic")
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.polish_requested, timeout=500) as sig:
        p.polish_button.click()
    provider, skill = sig.args[0], sig.args[1]
    assert provider == "anthropic"
    assert skill is None


def test_controls_lists_skills_from_dir(qtbot, tmp_path):
    (tmp_path / "xhs-tone.md").write_text("skill content", encoding="utf-8")
    (tmp_path / "b2b-tone.md").write_text("skill content", encoding="utf-8")
    p = ControlsPanel(skill_dir=tmp_path, provider_default="mock")
    qtbot.addWidget(p)
    items = [p.skill_combo.itemText(i) for i in range(p.skill_combo.count())]
    assert "无" in items
    assert "xhs-tone" in items
    assert "b2b-tone" in items
