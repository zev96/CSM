import pytest
from pathlib import Path
from csm_gui.pages.skills_page import SkillsPage
from csm_gui.config import AppConfig


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    (tmp_path / "beta.md").write_text("B", encoding="utf-8")
    return tmp_path


def test_page_selects_first_skill_on_load(qtbot, skill_dir):
    cfg = AppConfig(skill_dir=str(skill_dir))
    page = SkillsPage(config=cfg)
    qtbot.addWidget(page)
    page.list_panel.list_widget.setCurrentRow(0)
    page.list_panel._on_item_clicked()
    assert page.editor_panel.name_input.text() == "alpha"


def test_apply_config_rescans(qtbot, skill_dir, tmp_path):
    cfg = AppConfig(skill_dir=None)
    page = SkillsPage(config=cfg)
    qtbot.addWidget(page)
    cfg2 = AppConfig(skill_dir=str(skill_dir))
    page.apply_config(cfg2)
    items = [page.list_panel.list_widget.item(i).text()
             for i in range(page.list_panel.list_widget.count())]
    assert items == ["alpha", "beta"]


def test_switch_skill_with_dirty_prompts_confirm(qtbot, skill_dir, monkeypatch):
    cfg = AppConfig(skill_dir=str(skill_dir))
    page = SkillsPage(config=cfg)
    qtbot.addWidget(page)

    page.list_panel.list_widget.setCurrentRow(0)
    page.list_panel._on_item_clicked()
    page.editor_panel.editor.setPlainText("# dirty")
    assert page.editor_panel.is_dirty()

    monkeypatch.setattr(page, "_resolve_dirty", lambda: "discard")
    page.list_panel.list_widget.setCurrentRow(1)
    page.list_panel._on_item_clicked()
    assert page.editor_panel.name_input.text() == "beta"
    assert (skill_dir / "alpha.md").read_text(encoding="utf-8") == "A"
