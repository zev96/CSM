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
    page = ArticlePage()
    qtbot.addWidget(page)
    sentinel = object()
    page.load_result(sentinel)
    assert page.current_result is sentinel
