from csm_gui.pages.article_page import ArticlePage


def test_article_page_has_three_panels(qtbot):
    page = ArticlePage()
    qtbot.addWidget(page)
    assert page.slot_panel is not None
    assert page.preview_panel is not None
    assert page.controls_panel is not None
    # splitter has 2 widgets: left placeholder + right_splitter
    assert page.splitter.count() == 2


def test_article_page_clear_empties_markdown(qtbot):
    page = ArticlePage()
    qtbot.addWidget(page)
    page.markdown_view.set_draft("something")
    page.markdown_view.set_polished("something else")
    page.clear()
    assert page.markdown_view.draft_edit.toPlainText() == ""
    assert page.markdown_view.polished_edit.toPlainText() == ""


def test_article_page_load_result_renders_inputs(qtbot):
    from csm_core.template.schema import Template, LiteralBlock
    from csm_core.assembler.plan import AssemblyPlan

    page = ArticlePage()
    qtbot.addWidget(page)
    template = Template(id="t", name="t", product="p", blocks=[
        LiteralBlock(id="x", text="x"),
    ])
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0)
    page.load_result(template, plan, "draft-text", "polished-text")
    assert "draft-text" in page.markdown_view.draft_edit.toPlainText()
    assert "polished-text" in page.markdown_view.polished_edit.toPlainText()


def test_markdown_view_sets_draft_and_polished(qtbot):
    from csm_gui.widgets.markdown_view import MarkdownView
    view = MarkdownView()
    qtbot.addWidget(view)
    view.set_draft("# Draft\n\ncontent")
    view.set_polished("# Polished\n\nbetter content")
    assert "Draft" in view.draft_edit.toPlainText()
    assert "Polished" in view.polished_edit.toPlainText()
    # set_polished switches the pivot — a silent regression here is easy to miss
    assert view._pivot.currentRouteKey() == "polished"
