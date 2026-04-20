from csm_gui.pages.article_page import ArticlePage


def test_article_page_has_three_panels(qtbot):
    page = ArticlePage()
    qtbot.addWidget(page)
    assert page.slot_panel is not None
    assert page.preview_panel is not None
    assert page.controls_panel is not None
    assert page.splitter.count() == 3


def test_article_page_clear_sets_current_result_none(qtbot):
    page = ArticlePage()
    qtbot.addWidget(page)
    page.clear()
    assert page.current_result is None


def test_article_page_load_result_stores_reference(qtbot):
    from types import SimpleNamespace
    from csm_core.template.schema import Template
    from csm_core.assembler.plan import AssemblyPlan

    page = ArticlePage()
    qtbot.addWidget(page)
    template = Template(id="t", name="t", product="p", slots=[], render_order=[])
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[])
    result_obj = SimpleNamespace(plan=plan)
    page.load_result(template, result_obj)
    assert page.current_result is result_obj
