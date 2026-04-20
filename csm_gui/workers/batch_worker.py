"""QThread wrapper for csm_core.batch.runner.run_batch."""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from csm_core.batch.runner import run_batch
from csm_core.llm.client import LLMClient


class BatchWorker(QThread):
    item_started = pyqtSignal(int, str)
    item_finished = pyqtSignal(object)
    batch_finished = pyqtSignal(object)

    def __init__(
        self,
        keywords: list[str],
        template_path: Path,
        vault_root: Path,
        out_dir: Path,
        llm_client: LLMClient,
        seed: int,
        parent=None,
    ):
        super().__init__(parent)
        self._keywords = keywords
        self._template_path = Path(template_path)
        self._vault_root = Path(vault_root)
        self._out_dir = Path(out_dir)
        self._llm_client = llm_client
        self._seed = seed
        self._cancel_flag = False

    def request_cancel(self) -> None:
        self._cancel_flag = True

    def _emit_item_started(self, index: int, keyword: str) -> None:
        self.item_started.emit(index, keyword)
        # Yield so queued slots on the main thread (e.g. a listener that calls
        # request_cancel) run before the next iteration of the batch loop.
        self.msleep(10)

    def _emit_item_finished(self, item) -> None:
        self.item_finished.emit(item)
        self.msleep(10)

    def run(self) -> None:  # type: ignore[override]
        report = run_batch(
            keywords=self._keywords,
            template_path=self._template_path,
            vault_root=self._vault_root,
            out_dir=self._out_dir,
            llm_client=self._llm_client,
            seed=self._seed,
            on_item_started=self._emit_item_started,
            on_item_finished=self._emit_item_finished,
            should_cancel=lambda: self._cancel_flag,
        )
        self.batch_finished.emit(report)
