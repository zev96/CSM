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


def test_article_page_load_result_populates_pick_list(qtbot):
    from csm_gui.pages.article_page import ArticlePage
    from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant

    page = ArticlePage()
    qtbot.addWidget(page)
    plan = AssemblyPlan(
        keyword="kw", template_id="t", seed=1,
        results=[BlockResult(
            block_id="nl", kind="numbered_list",
            picks=[PickedVariant(note_id="n1", variant_index=0, text="hi")],
            meta={"number_style": "1.", "item_separator": "\n\n"},
        )],
    )
    page.load_result(template=None, plan=plan, draft="draft", final_text="")
    assert page.pick_list_panel.row_count() == 1
