from pathlib import Path


def test_template_manager_page_has_two_tabs(qtbot, tmp_path):
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    page = TemplateManagerPage(AppConfig())
    qtbot.addWidget(page)

    assert hasattr(page, "tabs")
    labels = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert labels == ["模板", "框架"]


def test_template_manager_page_framework_tab_has_editor(qtbot):
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    page = TemplateManagerPage(AppConfig())
    qtbot.addWidget(page)
    assert hasattr(page, "framework_list_panel")
    assert hasattr(page, "framework_editor_panel")
