"""QThread worker running the csm_core pipeline with stage signals."""
from __future__ import annotations
import traceback
from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.pipeline import GenerateRequest, GenerateResult
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.loader import load_template
from csm_core.assembler.constraints import assemble_plan
from csm_core.llm.prompts import build_prompt, PromptInputs
from csm_core.export.markdown import export_article


class GenerateWorker(QThread):
    """Runs the generate pipeline step-by-step, emitting stage_changed.

    Note: ``finished`` intentionally shadows ``QThread.finished`` so we can
    carry the ``GenerateResult`` payload. Callers using ``qtbot.waitSignal``
    will receive the overridden signal.
    """

    stage_changed = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, req: GenerateRequest, parent=None):
        super().__init__(parent)
        self._req = req

    def run(self) -> None:  # noqa: D401
        req = self._req
        try:
            self.stage_changed.emit("扫描资料库")
            index = scan_vault(req.vault_root)
            registry = build_brand_registry(req.vault_root)

            self.stage_changed.emit("加载模板")
            template = load_template(req.template_path)

            self.stage_changed.emit("采样 slots")
            plan = assemble_plan(
                keyword=req.keyword,
                template=template,
                index=index,
                registry=registry,
                seed=req.seed,
                user_config=req.user_config or {},
            )

            self.stage_changed.emit("组装 prompt")
            draft = "\n\n".join(
                "\n\n".join(p.text for p in s.picks)
                for s in plan.slots
                if s.picks
            )
            system, user = build_prompt(PromptInputs(
                template_system_prompt=template.system_prompt_default,
                user_skill_prompt=req.user_skill_prompt,
                seo=template.seo_defaults,
                keyword=req.keyword,
                draft=draft,
            ))

            self.stage_changed.emit("调用 LLM")
            final_text = req.llm_client.complete(system=system, user=user)

            self.stage_changed.emit("导出")
            paths = export_article(
                out_dir=req.out_dir,
                keyword=req.keyword,
                final_text=final_text,
                plan=plan,
                prompt_snapshot={
                    "system": system,
                    "user": user,
                    "provider": type(req.llm_client).__name__,
                },
            )
            result = GenerateResult(
                markdown_path=paths["markdown"],
                assembly_json_path=paths["assembly_json"],
                plan=plan,
                final_text=final_text,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
