"""Background workers for dedup analysis and index building.

Both workers are QThread subclasses that emit finished/progress signals.
They run synchronously in their own thread; the analyzer is shared
(thread-affine — only one worker should touch a given analyzer at a time).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.dedup.analyzer import DedupAnalyzer
from csm_core.dedup.report import DuplicateReport

logger = logging.getLogger(__name__)


class DedupAnalyzeWorker(QThread):
    """Analyze ``text`` against ``kind``'s index. Emits ``finished(report)``."""

    finished = pyqtSignal(DuplicateReport)

    def __init__(self, analyzer: DedupAnalyzer, text: str, kind: str,
                 parent=None):
        super().__init__(parent)
        self._analyzer = analyzer
        self._text = text
        self._kind = kind

    def run(self) -> None:
        try:
            report = self._analyzer.analyze(self._text, kind=self._kind)
        except Exception as exc:
            logger.warning("DedupAnalyzeWorker failed: %s", exc)
            report = DuplicateReport.empty(self._kind)
        self.finished.emit(report)


class DedupBuildWorker(QThread):
    """Build a fresh index for ``kind`` by scanning ``root``.

    Emits ``progress(done, total)`` periodically and ``finished()`` at end.
    """

    progress = pyqtSignal(int, int)
    finished = pyqtSignal()

    def __init__(self, analyzer: DedupAnalyzer, root: Path, kind: str,
                 parent=None):
        super().__init__(parent)
        self._analyzer = analyzer
        self._root = Path(root)
        self._kind = kind

    def run(self) -> None:
        try:
            self._analyzer.build_index(
                self._root,
                kind=self._kind,
                progress_cb=lambda done, total: self.progress.emit(done, total),
            )
        except Exception as exc:
            logger.warning("DedupBuildWorker failed: %s", exc)
        self.finished.emit()
