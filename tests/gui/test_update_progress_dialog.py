"""UpdateProgressDialog: progress bar + cancel button + speed display."""
from csm_gui.widgets.update_progress_dialog import UpdateProgressDialog


def test_progress_dialog_initial_state(qtbot):
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    assert dlg.progress_bar.value() == 0
    assert dlg.cancel_button.isEnabled()


def test_progress_dialog_set_progress(qtbot):
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_progress(500_000, 1_000_000)
    assert dlg.progress_bar.value() == 50  # percent


def test_progress_dialog_set_progress_unknown_total(qtbot):
    """If total is 0/unknown, still don't crash; show indeterminate."""
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_progress(500_000, 0)


def test_progress_dialog_cancel_emits(qtbot):
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.cancel_requested, timeout=1000):
        dlg.cancel_button.click()
    assert dlg.is_cancelled() is True
