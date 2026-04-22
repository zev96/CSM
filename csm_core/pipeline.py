"""End-to-end orchestration: keyword + template → article."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .vault.scanner import scan_vault
from .vault.brand_registry import build_brand_registry
from .template.loader import load_template
from .assembler.constraints import assemble_plan
from .assembler.plan import AssemblyPlan
from .assembler.render import compose_draft
from .llm.client import LLMClient
from .llm.prompts import build_prompt, PromptInputs
from .export.markdown import export_article


STAGES = ("扫描资料库", "加载模板", "采样 blocks", "组装 prompt", "调用 LLM", "导出")


@dataclass
class GenerateRequest:
    keyword: str
    vault_root: Path
    template_path: Path
    out_dir: Path
    llm_client: LLMClient
    user_skill_prompt: str | None = None
    seed: int = 0
    user_config: dict[str, int] | None = None
    draft_only: bool = False


@dataclass
class GenerateResult:
    markdown_path: str
    assembly_json_path: str
    plan: AssemblyPlan
    final_text: str


def generate(
    req: GenerateRequest,
    on_stage: Callable[[str], None] | None = None,
) -> GenerateResult:
    def _emit(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    _emit("扫描资料库")
    index = scan_vault(req.vault_root)
    registry = build_brand_registry(req.vault_root)

    _emit("加载模板")
    template = load_template(req.template_path)

    _emit("采样 blocks")
    plan = assemble_plan(
        keyword=req.keyword, template=template,
        index=index, registry=registry,
        seed=req.seed, user_config=req.user_config or {},
    )

    _emit("组装 prompt")
    draft = compose_draft(plan)

    if req.draft_only:
        return GenerateResult(
            markdown_path="", assembly_json_path="",
            plan=plan, final_text="",
        )

    system, user = build_prompt(PromptInputs(
        template_system_prompt=template.system_prompt_default,
        user_skill_prompt=req.user_skill_prompt,
        seo=template.seo_defaults,
        keyword=req.keyword, draft=draft,
    ))

    _emit("调用 LLM")
    final_text = req.llm_client.complete(system=system, user=user)

    _emit("导出")
    paths = export_article(
        out_dir=req.out_dir, keyword=req.keyword, final_text=final_text,
        plan=plan,
        prompt_snapshot={
            "system": system, "user": user,
            "provider": type(req.llm_client).__name__,
        },
    )
    return GenerateResult(
        markdown_path=paths["markdown"],
        assembly_json_path=paths["assembly_json"],
        plan=plan, final_text=final_text,
    )
