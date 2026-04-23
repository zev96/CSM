from csm_gui.widgets.controls_panel import ControlsPanel


def test_controls_emits_rerun_all(qtbot):
    p = ControlsPanel(skill_dir=None)
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.rerun_all_requested, timeout=500):
        p.rerun_all_button.click()


def test_controls_emits_polish_with_no_skill(qtbot):
    p = ControlsPanel(skill_dir=None)
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.polish_requested, timeout=500) as sig:
        p.polish_button.click()
    # Polish signal now carries only the skill path — provider is resolved
    # from AppConfig at the main-window layer.
    assert sig.args[0] is None


def test_controls_emits_polish_with_skill(qtbot, tmp_path):
    (tmp_path / "xhs-tone.md").write_text("x", encoding="utf-8")
    p = ControlsPanel(skill_dir=tmp_path)
    qtbot.addWidget(p)
    idx = p.skill_combo.findText("xhs-tone")
    assert idx >= 0
    p.skill_combo.setCurrentIndex(idx)
    with qtbot.waitSignal(p.polish_requested, timeout=500) as sig:
        p.polish_button.click()
    assert sig.args[0] == tmp_path / "xhs-tone.md"


def test_controls_lists_skills_from_dir(qtbot, tmp_path):
    (tmp_path / "xhs-tone.md").write_text("skill content", encoding="utf-8")
    (tmp_path / "b2b-tone.md").write_text("skill content", encoding="utf-8")
    p = ControlsPanel(skill_dir=tmp_path)
    qtbot.addWidget(p)
    items = [p.skill_combo.itemText(i) for i in range(p.skill_combo.count())]
    assert "无" in items
    assert "xhs-tone" in items
    assert "b2b-tone" in items


def test_controls_emits_export(qtbot):
    p = ControlsPanel(skill_dir=None)
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.export_requested, timeout=500):
        p.export_button.click()


def test_set_skill_dir_rebuilds_without_duplicates(qtbot, tmp_path):
    (tmp_path / "one.md").write_text("x", encoding="utf-8")
    p = ControlsPanel(skill_dir=tmp_path)
    qtbot.addWidget(p)
    # Call again — previously we'd double-populate if clear was forgotten.
    p.set_skill_dir(tmp_path)
    items = [p.skill_combo.itemText(i) for i in range(p.skill_combo.count())]
    assert items.count("one") == 1
    assert items.count("无") == 1


def test_set_provider_default_is_noop(qtbot):
    # Provider combo was removed — this setter is a compatibility shim that
    # must not raise.
    p = ControlsPanel(skill_dir=None)
    qtbot.addWidget(p)
    p.set_provider_default("deepseek")
    p.set_provider_default("bogus")


import pytest
from pathlib import Path


def test_preselect_sets_combo(qtbot, tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    (tmp_path / "beta.md").write_text("B", encoding="utf-8")
    panel = ControlsPanel(skill_dir=tmp_path, preferred_skill="beta")
    qtbot.addWidget(panel)
    assert panel.skill_combo.currentText() == "beta"


def test_preselect_unknown_falls_back_to_wu(qtbot, tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    panel = ControlsPanel(skill_dir=tmp_path, preferred_skill="nonexistent")
    qtbot.addWidget(panel)
    assert panel.skill_combo.currentText() == "无"


def test_set_preferred_skill_after_construction(qtbot, tmp_path):
    (tmp_path / "x.md").write_text("x", encoding="utf-8")
    panel = ControlsPanel(skill_dir=tmp_path)
    qtbot.addWidget(panel)
    panel.set_preferred_skill("x")
    assert panel.skill_combo.currentText() == "x"
