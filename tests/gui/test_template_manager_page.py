def test_template_manager_page_has_panels(qtbot):
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    page = TemplateManagerPage(AppConfig())
    qtbot.addWidget(page)

    assert hasattr(page, "list_panel")
    assert hasattr(page, "editor_panel")


def test_template_manager_page_no_framework_panels(qtbot):
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    page = TemplateManagerPage(AppConfig())
    qtbot.addWidget(page)

    assert not hasattr(page, "framework_list_panel")
    assert not hasattr(page, "framework_editor_panel")


def test_show_event_rescans_skill_dir(qtbot, tmp_path):
    """Regression: the default-skill combo did not pick up skills
    added in the Skills page without an app restart. ``showEvent``
    must re-scan the configured skill_dir each time the page is
    brought to front so the combo stays in sync."""
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    skill_dir = tmp_path / "skills"; skill_dir.mkdir()
    (skill_dir / "alpha.md").write_text("a", encoding="utf-8")
    cfg = AppConfig()
    cfg.skill_dir = str(skill_dir)
    page = TemplateManagerPage(cfg)
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    combo = page.editor_panel.default_skill_combo
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["（无）", "alpha"]
    # User creates a new skill via the Skills page (filesystem change)
    (skill_dir / "beta.md").write_text("b", encoding="utf-8")
    # Hide + re-show (simulates nav switch away and back)
    page.hide()
    page.show()
    qtbot.waitExposed(page)
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["（无）", "alpha", "beta"]
