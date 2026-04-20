"""QThread for running an LLM complete() call off the UI thread."""
from __future__ import annotations
import traceback
from PyQt6.QtCore import QThread, pyqtSignal
from csm_core.llm.client import LLMClient


class PolishWorker(QThread):
    finished = pyqtSignal(str)  # intentionally shadows QThread.finished — carries polished text
    failed = pyqtSignal(str)

    def __init__(self, client: LLMClient, system: str, user: str, parent=None):
        super().__init__(parent)
        self._client = client
        self._system = system
        self._user = user

    def run(self) -> None:  # type: ignore[override]
        try:
            text = self._client.complete(system=self._system, user=self._user)
            self.finished.emit(text)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
