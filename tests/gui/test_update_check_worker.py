"""UpdateCheckWorker: runs check_for_update in a QThread."""
from unittest.mock import patch
from csm_gui.workers.update_check_worker import UpdateCheckWorker
from csm_core.updater_client.checker import CheckResult
from csm_core.updater_client.manifest import UpdateInfo


def _info(version="0.2.0"):
    return UpdateInfo(
        version=version, tag_name=f"v{version}",
        zip_url="u", manifest_url="m",
        changelog="cl", published_at="t", asset_size=1,
    )


def test_check_worker_emits_finished_with_result(qtbot):
    fake = CheckResult(has_update=True, info=_info(), error=None)
    with patch("csm_gui.workers.update_check_worker.check_for_update",
               return_value=fake):
        worker = UpdateCheckWorker(
            repo="x/y", token="t", current_version="0.1.0",
        )
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
    assert blocker.args[0] is fake


def test_check_worker_emits_on_error_too(qtbot):
    """If checker returns error result, worker still emits a CheckResult with error set."""
    err_result = CheckResult(False, None, "network: dns failed")
    with patch("csm_gui.workers.update_check_worker.check_for_update",
               return_value=err_result):
        worker = UpdateCheckWorker(
            repo="x/y", token="t", current_version="0.1.0",
        )
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
    result = blocker.args[0]
    assert result.has_update is False
    assert result.error is not None
