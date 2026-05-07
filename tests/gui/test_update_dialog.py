"""UpdateDialog: shows version info + changelog + "立即升级 / 稍后再说" buttons."""
from csm_gui.widgets.update_dialog import UpdateDialog
from csm_core.updater_client.manifest import UpdateInfo


def _info(version="0.2.0"):
    return UpdateInfo(
        version=version, tag_name=f"v{version}",
        zip_url="u", manifest_url="m",
        changelog="### Added\n- 系统托盘\n- 内容查重\n",
        published_at="2026-05-07T08:00:00Z", asset_size=1_000_000,
    )


def test_dialog_renders_versions(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    text = dlg.summary_label.text()
    assert "0.1.0" in text
    assert "0.2.0" in text


def test_dialog_renders_changelog(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    cl = dlg.changelog_view.toPlainText() if hasattr(dlg.changelog_view, "toPlainText") else dlg.changelog_view.text()
    assert "系统托盘" in cl


def test_dialog_upgrade_button_emits(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.upgrade_requested, timeout=1000):
        dlg.upgrade_button.click()


def test_dialog_later_button_closes(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    dlg.later_button.click()
    assert dlg.result() == 0  # QDialog.Rejected
