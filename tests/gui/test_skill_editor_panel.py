import pytest
from pathlib import Path
from csm_gui.widgets.skill_editor_panel import SkillEditorPanel


@pytest.fixture
def skill_file(tmp_path):
    p = tmp_path / "alpha.md"
    p.write_text("# Alpha\n\nhello", encoding="utf-8")
    return p


def test_load_populates_editor(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    assert panel.editor.toPlainText() == "# Alpha\n\nhello"
    assert panel.name_input.text() == "alpha"
    assert panel.is_dirty() is False


def test_edit_marks_dirty(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.editor.setPlainText("# changed")
    assert panel.is_dirty() is True


def test_save_writes_and_clears_dirty(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.editor.setPlainText("# saved")
    assert panel.save() is True
    assert skill_file.read_text(encoding="utf-8") == "# saved"
    assert panel.is_dirty() is False


def test_rename_via_name_input(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.name_input.setText("renamed")
    panel.save()
    assert not skill_file.exists()
    assert (skill_file.parent / "renamed.md").is_file()


def test_rename_collision_aborts_save(qtbot, skill_file, tmp_path):
    (tmp_path / "other.md").write_text("other", encoding="utf-8")
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.name_input.setText("other")
    assert panel.save() is False
    assert skill_file.is_file()
