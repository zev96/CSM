"""QThread that runs title generation off the UI thread."""
from __future__ import annotations
import traceback
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.llm.client import LLMClient
from csm_core.title.generator import generate_titles, fallback_title


class TitleWorker(QThread):
    """Wraps :func:`csm_core.title.generator.generate_titles`.

    The worker always calls ``finished.emit(list)`` — the generator owns
    the fallback path internally, so even on an LLM hiccup the UI gets at
    least one usable title and never has to special-case a failed run.
    ``failed`` is reserved for unexpected programming errors (e.g. vault
    path doesn't exist) and carries a traceback for the log.

    ``llm_failed`` is a *non-fatal* warning: it fires when the generator
    silently fell back to the mechanical title (LLM unreachable / kept
    failing validation). The UI surfaces this as a toast so the user
    knows their AI config is broken instead of staring at a templated
    title and wondering why it doesn't look AI-polished.
    """

    finished = pyqtSignal(list)  # list[str] — candidate titles
    failed = pyqtSignal(str)
    llm_failed = pyqtSignal(str)  # non-fatal: AI couldn't produce, fallback used

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
            # Detect the silent-fallback path. ``generate_titles`` returns
            # exactly ``[fallback_title(keyword)]`` only when the LLM call
            # raised every attempt OR all candidates failed validation —
            # in either case the user got a mechanical title, not AI.
            if len(titles) == 1 and titles[0] == fallback_title(self._keyword):
                self.llm_failed.emit(
                    "AI 标题生成未返回有效结果，已使用默认标题。"
                    "请检查「设置 → 模型」的 API Key / 模型名 / 网络。"
                )
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
