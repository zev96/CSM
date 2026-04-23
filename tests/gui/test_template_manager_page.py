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
