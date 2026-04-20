"""ArticleController — owns article-workflow state off of MainWindow.

Contract (see docs/superpowers/specs/2026-04-20-plan-c-refactor-and-batch-design.md):
- Owns current_result, template, reroll counter, vault cache, workers.
- Emits signals; never calls InfoBar or switchTo directly.
- Never imports widget classes.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from csm_core.pipeline import GenerateResult
from csm_core.template.schema import Template
from ..config import AppConfig


class ArticleController(QObject):
    generated = pyqtSignal(object)           # GenerateResult
    generate_failed = pyqtSignal(str)
    reroll_completed = pyqtSignal(object)    # AssemblyPlan
    polished = pyqtSignal(str)
    polish_failed = pyqtSignal(str)
    exported = pyqtSignal(dict)              # {"markdown": path, "assembly_json": path}
    export_failed = pyqtSignal(str)
    plan_warnings = pyqtSignal(list)         # list[str]
    busy_changed = pyqtSignal(bool)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config: AppConfig = config
        self._current_result: GenerateResult | None = None
        self._current_template: Template | None = None
        self._last_template_path: Path | None = None
        self._reroll_counter: int = 0
        self._vault_cache: tuple[Path, float, object, object] | None = None
        self._generate_worker = None
        self._polish_worker = None

    # --- public API (stubs filled in by later tasks) ---

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        # Invalidate vault cache if root changed; full mtime check lives in _get_vault.
        if self._vault_cache is not None:
            if self._config.vault_root is None or str(self._vault_cache[0]) != self._config.vault_root:
                self._vault_cache = None

    def request_generate(self, payload: dict) -> bool:
        raise NotImplementedError  # Task 3

    def reroll_slot(self, slot_id: str, user_config: dict) -> None:
        raise NotImplementedError  # Task 4

    def polish(self, provider: str, skill_path: Path | None) -> None:
        raise NotImplementedError  # Task 5

    def export(self) -> None:
        raise NotImplementedError  # Task 6

    def is_busy(self) -> bool:
        gen_busy = self._generate_worker is not None and self._generate_worker.isRunning()
        polish_busy = self._polish_worker is not None and self._polish_worker.isRunning()
        return gen_busy or polish_busy

    # --- internals ---

    def _get_vault(self, vault_root: Path):
        from csm_core.vault.scanner import scan_vault
        from csm_core.vault.brand_registry import build_brand_registry
        mtime = vault_root.stat().st_mtime
        if (
            self._vault_cache is None
            or self._vault_cache[0] != vault_root
            or self._vault_cache[1] != mtime
        ):
            index = scan_vault(vault_root)
            registry = build_brand_registry(vault_root)
            self._vault_cache = (vault_root, mtime, index, registry)
        return self._vault_cache[2], self._vault_cache[3]
