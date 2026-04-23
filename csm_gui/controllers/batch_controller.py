"""BatchController — lifecycle for BatchWorker + per-batch subdirectory."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from ..config import AppConfig
from ..llm_factory import build_client
from ..workers.batch_worker import BatchWorker


class BatchController(QObject):
    batch_started = pyqtSignal(object)
    batch_progress = pyqtSignal(int, int, str)
    item_finished = pyqtSignal(object)
    batch_completed = pyqtSignal(object)
    batch_cancelled = pyqtSignal(object)
    batch_failed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._worker: BatchWorker | None = None
        self._cancelling = False
        self._total = 0
        self._done = 0

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def start_batch(self, payload: dict) -> bool:
        if self.is_busy():
            return False
        if not self._config.out_dir:
            return False
        vault_root = Path(payload["vault_root"])
        if not vault_root.exists():
            return False
        cleaned: list[str] = []
        seen: set[str] = set()
        for k in payload["keywords"]:
            k = k.strip()
            if not k or k in seen:
                continue
            seen.add(k)
            cleaned.append(k)
        if not cleaned:
            return False

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        batch_dir = Path(self._config.out_dir) / f"batch-{stamp}"
        batch_dir.mkdir(parents=True, exist_ok=False)

        client = build_client(self._config, payload["provider"])
        self._total = len(cleaned)
        self._done = 0
        self._cancelling = False

        self._worker = BatchWorker(
            keywords=cleaned,
            template_path=Path(payload["template_path"]),
            vault_root=vault_root,
            out_dir=batch_dir,
            llm_client=client,
            seed=int(payload.get("seed", self._config.last_seed)),
            skill_dir=Path(self._config.skill_dir) if self._config.skill_dir else None,
            parent=self,
        )
        self._worker.item_started.connect(self._on_item_started)
        self._worker.item_finished.connect(self._on_item_finished)
        self._worker.batch_finished.connect(self._on_batch_finished)
        self._worker.start()
        self.busy_changed.emit(True)
        return True

    def cancel(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self._cancelling = True
        self._worker.request_cancel()

    def _on_item_started(self, index: int, keyword: str) -> None:
        self.batch_progress.emit(self._done, self._total, keyword)

    def _on_item_finished(self, item) -> None:
        self._done += 1
        self.item_finished.emit(item)
        self.batch_progress.emit(self._done, self._total, "")

    def _on_batch_finished(self, report) -> None:
        if self._cancelling:
            self.batch_cancelled.emit(report)
        else:
            self.batch_completed.emit(report)
        self.busy_changed.emit(False)
