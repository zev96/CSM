"""QThread that runs title generation off the UI thread."""
from __future__ import annotations
import traceback
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.llm.client import LLMClient
from csm_core.title.generator import generate_titles


class TitleWorker(QThread):
    """Wraps :func:`csm_core.title.generator.generate_titles`.

    The worker always calls ``finished.emit(list)`` — the generator owns
    the fallback path internally, so even on an LLM hiccup the UI gets at
    least one usable title and never has to special-case a failed run.
    ``failed`` is reserved for unexpected programming errors (e.g. vault
    path doesn't exist) and carries a traceback for the log.
    """

    finished = pyqtSignal(list)  # list[str] — candidate titles
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        keyword: str,
        template_type: str | None,
        vault_root: Path,
        llm_client: LLMClient,
        parent=None,
    ):
        super().__init__(parent)
        self._keyword = keyword
        self._template_type = template_type
        self._vault_root = Path(vault_root)
        self._client = llm_client

    def run(self) -> None:  # type: ignore[override]
        try:
            titles = generate_titles(
                keyword=self._keyword,
                template_type=self._template_type,
                vault_root=self._vault_root,
                llm_client=self._client,
            )
            self.finished.emit(titles)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
