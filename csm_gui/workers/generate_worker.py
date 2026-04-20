"""QThread worker that runs pipeline.generate off the UI thread."""
from __future__ import annotations
import traceback
from PyQt6.QtCore import QThread, pyqtSignal
from csm_core.pipeline import GenerateRequest, generate


class GenerateWorker(QThread):
    """Runs csm_core.pipeline.generate on a background thread.

    Note: ``finished`` intentionally shadows the built-in ``QThread.finished``
    signal so callers can receive the GenerateResult payload directly.
    """

    stage_changed = pyqtSignal(str)
    finished = pyqtSignal(object)  # GenerateResult
    failed = pyqtSignal(str)

    def __init__(self, request: GenerateRequest, parent=None):
        super().__init__(parent)
        self._request = request

    def run(self) -> None:  # type: ignore[override]
        try:
            result = generate(self._request, on_stage=self.stage_changed.emit)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
