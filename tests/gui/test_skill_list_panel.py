import pytest
from pathlib import Path
from csm_gui.widgets.skill_list_panel import SkillListPanel


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    (tmp_path / "beta.md").write_text("B", encoding="utf-8")
    (tmp_path / "README.txt").write_text("ignore me", encoding="utf-8")
    return tmp_path


def test_panel_lists_md_files_sorted(qtbot, skill_dir):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    items = [p.list_widget.item(i).text() for i in range(p.list_widget.count())]
    assert items == ["alpha", "beta"]


def test_panel_emits_selected_signal(qtbot, skill_dir):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    with qtbot.waitSignal(p.skill_selected, timeout=1000) as blocker:
        p.list_widget.setCurrentRow(1)
        p._on_item_clicked()
    assert blocker.args[0].name == "beta.md"


def test_panel_new_skill_writes_skeleton(qtbot, skill_dir, monkeypatch):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    monkeypatch.setattr(p, "_prompt_new_name", lambda: "gamma")
    p._on_new()
    target = skill_dir / "gamma.md"
    assert target.is_file()
    assert "# 新 Skill" in target.read_text(encoding="utf-8")


def test_panel_new_skill_refuses_collision(qtbot, skill_dir, monkeypatch):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    monkeypatch.setattr(p, "_prompt_new_name", lambda: "alpha")
    before = (skill_dir / "alpha.md").read_text(encoding="utf-8")
    p._on_new()
    after = (skill_dir / "alpha.md").read_text(encoding="utf-8")
    assert before == after


def test_panel_delete_moves_to_trash(qtbot, skill_dir, monkeypatch):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    p.list_widget.setCurrentRow(0)
    monkeypatch.setattr(p, "_confirm_delete", lambda name: True)
    p._on_delete()
    assert not (skill_dir / "alpha.md").is_file()
    assert (skill_dir / ".trash" / "alpha.md").is_file()
