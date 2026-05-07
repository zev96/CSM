"""Background worker that runs check_for_update off the UI thread."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.updater_client.checker import check_for_update, CheckResult

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """Runs check_for_update on a background thread.

    Emits ``finished(CheckResult)`` once complete — always, even on error
    (the error is embedded in the CheckResult.error field so the UI can
    decide whether to surface it).
    """

    finished = pyqtSignal(object)  # CheckResult

    def __init__(self, *, repo: str, token: str, current_version: str,
                 parent=None):
        super().__init__(parent)
        self._repo = repo
        self._token = token
        self._current_version = current_version

    def run(self) -> None:  # type: ignore[override]
        try:
            result = check_for_update(
                repo=self._repo,
                token=self._token,
                current_version=self._current_version,
            )
        except Exception as exc:  # noqa: BLE001 — worker boundary
            logger.warning("UpdateCheckWorker unexpected error: %s", exc)
            result = CheckResult(has_update=False, info=None,
                                 error=f"unexpected error: {exc}")
        self.finished.emit(result)
