"""ArticleController — owns article-workflow state off of MainWindow.

Contract (see docs/superpowers/specs/2026-04-20-plan-c-refactor-and-batch-design.md):
- Owns current_result, template, vault cache, workers.
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
from ..workers.polish_worker import PolishWorker
from ..workers.title_worker import TitleWorker
from ..llm_factory import build_client
from csm_core.llm.prompts import build_prompt, PromptInputs
from csm_core.assembler.render import compose_draft
from csm_core.export.markdown import export_article


class ArticleController(QObject):
    generated = pyqtSignal(object)           # GenerateResult
    generate_failed = pyqtSignal(str)
    polished = pyqtSignal(str)
    polish_failed = pyqtSignal(str)
    exported = pyqtSignal(dict)              # {"markdown": path, "assembly_json": path}
    export_failed = pyqtSignal(str)
    plan_warnings = pyqtSignal(list)         # list[str]
    busy_changed = pyqtSignal(bool)
    reroll_completed = pyqtSignal(object)    # AssemblyPlan
    reroll_failed = pyqtSignal(str)
    titles_ready = pyqtSignal(list)          # list[str] — candidate titles
    titles_failed = pyqtSignal(str)
    # Non-fatal — fires when title generation silently fell back to a
    # mechanical title (LLM unreachable or kept producing invalid output).
    # The UI surfaces this as a warning toast.
    titles_llm_failed = pyqtSignal(str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config: AppConfig = config
        self._current_result: GenerateResult | None = None
        self._current_template: Template | None = None
        self._last_template_path: Path | None = None
        self._vault_cache: tuple[Path, float, object, object] | None = None
        self._generate_worker = None
        self._polish_worker = None
        self._reroll_worker = None
        self._title_worker = None
        # Last payload accepted by ``request_generate`` — stored so
        # ``rerun_all`` can re-submit with a fresh seed without making the
        # UI round-trip back to the home page.
        self._last_payload: dict | None = None

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
            # Two-phase flow: only assemble the draft here. The user reviews
            # / edits, then triggers ``polish`` to spend the LLM call.
            draft_only=True,
            # Optional override — UI may pass a user-edited core keyword.
            # When absent, assembler auto-extracts from keyword.
            core_keyword=payload.get("core_keyword") or None,
        )
        self._generate_worker = GenerateWorker(req, self)
        self._generate_worker.finished.connect(self._on_generate_finished)
        self._generate_worker.failed.connect(self._on_generate_failed)
        self._generate_worker.start()
        self._last_payload = dict(payload)
        self.busy_changed.emit(True)

        # Fire title generation in parallel with draft assembly. The
        # worker is fire-and-forget — title results don't block the draft
        # flow and arrive via ``titles_ready`` whenever the LLM responds.
        self._fire_title_worker(payload)
        return True

    def _fire_title_worker(self, payload: dict) -> None:
        """Kick off auto-title generation alongside draft assembly.

        Reads the template once just to extract ``template_type``; we
        don't cache that on the controller because the user may have
        switched templates between runs. Failures are non-fatal —
        ``titles_failed`` only fires for unexpected exceptions; the
        generator itself returns a fallback title rather than raising
        when the LLM trips.
        """
        from csm_core.template.loader import load_template
        if self._title_worker is not None and self._title_worker.isRunning():
            # Don't pile up — let the previous run finish. The user can
            # cycle candidates manually if they ran 重新生成 quickly.
            return
        try:
            tpl = load_template(self._last_template_path)
        except Exception as exc:  # noqa: BLE001
            self.titles_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        client = build_client(self._config, payload["provider"])
        self._title_worker = TitleWorker(
            keyword=payload["keyword"],
            template_type=tpl.template_type,
            vault_root=Path(payload["vault_root"]),
            llm_client=client,
            parent=self,
        )
        self._title_worker.finished.connect(self._on_titles_finished)
        self._title_worker.failed.connect(self._on_titles_failed)
        self._title_worker.llm_failed.connect(self.titles_llm_failed.emit)
        self._title_worker.start()

    def _on_titles_finished(self, titles: list) -> None:
        # Generator never returns an empty list, but be defensive — UI
        # should still see at least a one-element list.
        if not titles:
            return
        self.titles_ready.emit(list(titles))

    def _on_titles_failed(self, msg: str) -> None:
        self.titles_failed.emit(msg)

    def rerun_all(self) -> bool:
        """Re-submit the last generate request with a freshly rolled seed.

        Used by the 重新随机 button on the article workspace. Returns False
        if there is nothing to re-run (no prior generate) or if a worker is
        still running.
        """
        if self._last_payload is None:
            return False
        if self._generate_worker is not None and self._generate_worker.isRunning():
            return False
        import random
        # Roll a new seed so the sampler picks differently. Store it on config
        # so downstream code that reads ``last_seed`` sees a consistent value.
        self._config.last_seed = random.randint(1, 99999)
        return self.request_generate(self._last_payload)

    def reroll_pick(self, block_id: str, pick_index: int) -> bool:
        """Reroll a single pick in the current plan.

        Returns False if no current article / worker busy — the caller should
        avoid firing again in that state. On success the new plan is emitted
        via ``reroll_completed`` and stored on the controller. On failure
        ``reroll_failed`` is emitted with a human-readable message.
        """
        if self._current_result is None or self._current_template is None:
            return False
        if self._reroll_worker is not None and self._reroll_worker.isRunning():
            return False
        if self._config.vault_root is None:
            self.reroll_failed.emit("VaultRootMissing: 请先在设置页配置资料库目录")
            return False

        vault_root = Path(self._config.vault_root)
        try:
            index, _registry = self._get_vault(vault_root)
        except Exception as exc:  # noqa: BLE001 — boundary, surface to UI
            self.reroll_failed.emit(f"{type(exc).__name__}: {exc}")
            return False

        from ..workers.reroll import RerollWorker
        self._reroll_worker = RerollWorker(
            plan=self._current_result.plan,
            block_id=block_id,
            pick_index=pick_index,
            template=self._current_template,
            vault_index=index,
            parent=self,
        )
        self._reroll_worker.finished.connect(self._on_reroll_finished)
        self._reroll_worker.failed.connect(self._on_reroll_failed)
        self._reroll_worker.start()
        self.busy_changed.emit(True)
        return True

    def _on_reroll_finished(self, new_plan) -> None:
        if self._current_result is not None:
            self._current_result.plan = new_plan
        self.reroll_completed.emit(new_plan)
        self.busy_changed.emit(False)

    def _on_reroll_failed(self, msg: str) -> None:
        self.reroll_failed.emit(msg)
        self.busy_changed.emit(False)

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
        self.generated.emit(result)
        if getattr(result.plan, "warnings", None):
            self.plan_warnings.emit(list(result.plan.warnings))
        self.busy_changed.emit(False)

    def _on_generate_failed(self, msg: str) -> None:
        self.generate_failed.emit(msg)
        self.busy_changed.emit(False)

    def polish(
        self,
        provider: str,
        skill_path: Path | None,
        draft_override: str | None = None,
    ) -> None:
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
        # Prefer the user-edited draft (from the editable 初稿 tab) over a
        # freshly re-composed one — otherwise manual tweaks are lost.
        draft = draft_override if draft_override is not None else compose_draft(plan)
        system, user = build_prompt(PromptInputs(
            user_skill_prompt=skill_text,
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

    def export(self, out_dir: str | None = None) -> None:
        if self._current_result is None:
            return
        target = out_dir or self._config.out_dir
        if not target:
            self.export_failed.emit("OutputDirectoryMissing: 请先在设置页配置输出目录")
            return
        if not (self._current_result.final_text or "").strip():
            # Draft-only flow: nothing to export until 润色 has produced 成文.
            self.export_failed.emit("NotPolished: 请先点击「润色」生成成文再导出")
            return
        try:
            paths = export_article(
                out_dir=Path(target),
                keyword=self._current_result.plan.keyword,
                final_text=self._current_result.final_text,
                plan=self._current_result.plan,
                fmt=self._config.export_format,
            )
        except Exception as exc:  # noqa: BLE001 — boundary, surface to UI
            self.export_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.exported.emit(paths)

    def clear(self) -> bool:
        """Drop the current article state (plan, template, last payload).

        Returns False if a worker is still running — the caller should wait
        for it to finish before clearing, otherwise the late ``generated`` /
        ``polished`` signal would repopulate state the user asked to wipe.
        """
        if self.is_busy():
            return False
        self._current_result = None
        self._current_template = None
        self._last_template_path = None
        self._last_payload = None
        return True

    def is_busy(self) -> bool:
        gen_busy = self._generate_worker is not None and self._generate_worker.isRunning()
        polish_busy = self._polish_worker is not None and self._polish_worker.isRunning()
        reroll_busy = self._reroll_worker is not None and self._reroll_worker.isRunning()
        # Title worker intentionally NOT counted — it's a background
        # affordance, not a step the user is waiting on.
        return gen_busy or polish_busy or reroll_busy

    # --- internals ---

    @property
    def current_template(self):
        """Read-only view of the loaded template (for UI rendering)."""
        return self._current_template

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
