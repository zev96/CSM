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
from ..workers.reroll import reroll_slot
from ..workers.polish_worker import PolishWorker
from ..llm_factory import build_client
from csm_core.llm.prompts import build_prompt, PromptInputs
from csm_core.assembler.render import compose_draft
from csm_core.export.markdown import export_article


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
        if self._current_result is None or self._current_template is None:
            return
        if not self._config.vault_root:
            return
        index, registry = self._get_vault(Path(self._config.vault_root))
        self._reroll_counter += 1
        new_plan = reroll_slot(
            slot_id=slot_id,
            template=self._current_template,
            index=index,
            registry=registry,
            current_plan=self._current_result.plan,
            counter=self._reroll_counter,
            user_config=user_config,
        )
        self._current_result.plan = new_plan
        self.reroll_completed.emit(new_plan)

    def polish(self, provider: str, skill_path: Path | None) -> None:
        if self._current_result is None or self._current_template is None:
            return
        if self._polish_worker is not None and self._polish_worker.isRunning():
            return

        skill_text: str | None = None
        if skill_path:
            try:
                skill_text = Path(skill_path).read_text(encoding="utf-8")
            except OSError as exc:
                self.polish_failed.emit(f"{type(exc).__name__}: {exc}")
                return

        template = self._current_template
        plan = self._current_result.plan
        draft = compose_draft(plan)
        system, user = build_prompt(PromptInputs(
            template_system_prompt=template.system_prompt_default,
            user_skill_prompt=skill_text,
            seo=template.seo_defaults,
            keyword=plan.keyword,
            draft=draft,
        ))
        client = build_client(self._config, provider)
        self._polish_worker = PolishWorker(client=client, system=system, user=user, parent=self)
        self._polish_worker.finished.connect(self._on_polish_finished)
        self._polish_worker.failed.connect(self._on_polish_failed)
        self._polish_worker.start()
        self.busy_changed.emit(True)

    def _on_polish_finished(self, text: str) -> None:
        if self._current_result is not None:
            self._current_result.final_text = text
        self.polished.emit(text)
        self.busy_changed.emit(False)

    def _on_polish_failed(self, msg: str) -> None:
        self.polish_failed.emit(msg)
        self.busy_changed.emit(False)

    def export(self) -> None:
        if self._current_result is None:
            return
        if not self._config.out_dir:
            self.export_failed.emit("OutputDirectoryMissing: 请先在设置页配置输出目录")
            return
        out_dir = Path(self._config.out_dir)
        try:
            paths = export_article(
                out_dir=out_dir,
                keyword=self._current_result.plan.keyword,
                final_text=self._current_result.final_text,
                plan=self._current_result.plan,
                prompt_snapshot={},
            )
        except Exception as exc:  # noqa: BLE001 — boundary, surface to UI
            self.export_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.exported.emit(paths)

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
