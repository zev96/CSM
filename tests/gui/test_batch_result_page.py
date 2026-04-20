from csm_core.batch.report import BatchReport, BatchItem
from csm_gui.pages.batch_result_page import BatchResultPage


def _mk_report(total=3):
    return BatchReport(
        batch_id="batch-20260420-120000",
        batch_dir="/tmp/batch-20260420-120000",
        started_at="2026-04-20T12:00:00",
        finished_at=None,
        template_path="/t/template.json",
        vault_root="/v",
        seed=0,
        total=total,
    )


def test_batch_result_page_on_started_resets_lists(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_item_finished(BatchItem(index=1, keyword="x", status="success"))
    page.on_batch_started(_mk_report())
    assert page.success_list.count() == 0
    assert page.failed_list.count() == 0


def test_batch_result_page_item_finished_sorts_by_status(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report())
    page.on_item_finished(BatchItem(index=1, keyword="ok", status="success"))
    page.on_item_finished(BatchItem(
        index=2, keyword="bad", status="failed",
        error_type="RuntimeError", error_message="broke",
    ))
    assert page.success_list.count() == 1
    assert page.failed_list.count() == 1


def test_batch_result_page_progress_update(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report(total=5))
    page.on_batch_progress(3, 5, "kw_current")
    assert page.progress_bar.value() == 3
    assert "kw_current" in page.current_label.text()


def test_batch_result_page_button_state_completed(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report())
    assert page.cancel_button.isVisible() is True or page.cancel_button.isEnabled()
    report = _mk_report()
    page.on_batch_completed(report)
    assert page.return_button.isEnabled() is True


def test_batch_result_page_cancel_button_transitions(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report())
    emitted = []
    page.cancel_requested.connect(lambda: emitted.append(True))
    page.cancel_button.click()
    assert emitted == [True]
    assert page.cancel_button.isEnabled() is False
    assert "取消中" in page.cancel_button.text()
