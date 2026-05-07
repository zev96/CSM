"""QThread wrapper for the (synchronous httpx) update check."""
from __future__ import annotations
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.updater_client.checker import CheckResult, check_for_update

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """Run check_for_update off the UI thread. Emits finished(CheckResult)."""

    finished = pyqtSignal(CheckResult)

    def __init__(self, *, repo: str, token: str, current_version: str,
                 timeout: float = 5.0, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._token = token
        self._current = current_version
        self._timeout = timeout

    def run(self) -> None:
        try:
            result = check_for_update(
                repo=self._repo,
                token=self._token,
                current_version=self._current,
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.warning("UpdateCheckWorker unexpected error: %s", exc)
            result = CheckResult(False, None, f"unexpected: {exc}")
        self.finished.emit(result)
