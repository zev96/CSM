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
from csm_core.pipeline import GenerateRequest
from ..workers.generate_worker import GenerateWorker
from ..llm_factory import build_client


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
        if not self._config.out_dir:
            return False
        if self._generate_worker is not None and self._generate_worker.isRunning():
            return False
        client = build_client(self._config, payload["provider"])
        self._last_template_path = Path(payload["template_path"])
        req = GenerateRequest(
            keyword=payload["keyword"],
            vault_root=Path(payload["vault_root"]),
            template_path=self._last_template_path,
            out_dir=Path(self._config.out_dir),
            llm_client=client,
            seed=self._config.last_seed,
        )
        self._generate_worker = GenerateWorker(req, self)
        self._generate_worker.finished.connect(self._on_generate_finished)
        self._generate_worker.failed.connect(self._on_generate_failed)
        self._generate_worker.start()
        self.busy_changed.emit(True)
        return True

    def _on_generate_finished(self, result) -> None:
        from csm_core.template.loader import load_template
        try:
            template = load_template(self._last_template_path)
        except Exception as exc:  # noqa: BLE001 — boundary, surface to UI
            self.generate_failed.emit(f"{type(exc).__name__}: {exc}")
            self.busy_changed.emit(False)
            return
        self._current_result = result
        self._current_template = template
        self._reroll_counter = 0
        self.generated.emit(result)
        if getattr(result.plan, "warnings", None):
            self.plan_warnings.emit(list(result.plan.warnings))
        self.busy_changed.emit(False)

    def _on_generate_failed(self, msg: str) -> None:
        self.generate_failed.emit(msg)
        self.busy_changed.emit(False)

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
