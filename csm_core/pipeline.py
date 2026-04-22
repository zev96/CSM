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
from .assembler.render import compose_draft, compose_draft_framed
from .framework.loader import load_framework, list_frameworks
from .llm.client import LLMClient
from .llm.prompts import build_prompt, PromptInputs
from .export.markdown import export_article


STAGES = ("扫描资料库", "加载模板", "采样 slots", "组装 prompt", "调用 LLM", "导出")


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
    # When True, the pipeline stops after ``compose_draft`` — no LLM call,
    # no export. Used by the two-phase UI flow: first assemble a draft the
    # user can review/edit, then run ``polish`` separately to produce 成文.
    draft_only: bool = False
    # Framework resolution:
    #   req.framework_id → template.default_framework → None (fall back to compose_draft)
    framework_id: str | None = None
    frameworks_dir: Path | None = None


@dataclass
class GenerateResult:
    markdown_path: str
    assembly_json_path: str
    plan: AssemblyPlan
    final_text: str


def _compose_draft_with_framework(
    plan: AssemblyPlan, template, req: "GenerateRequest",
) -> str:
    fw_id = req.framework_id or template.default_framework
    if not fw_id:
        return compose_draft(plan)

    fw_dir = req.frameworks_dir
    if fw_dir is None:
        return compose_draft(plan)

    for _name, path in list_frameworks(fw_dir):
        if path.stem == fw_id:
            fw = load_framework(path)
            return compose_draft_framed(plan, fw, {"keyword": req.keyword})
    # id referenced but not found: fall back (don't fail the pipeline)
    return compose_draft(plan)


def generate(req: GenerateRequest, on_stage: Callable[[str], None] | None = None) -> GenerateResult:
    def _emit(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    _emit("扫描资料库")
    index = scan_vault(req.vault_root)
    registry = build_brand_registry(req.vault_root)

    _emit("加载模板")
    template = load_template(req.template_path)

    _emit("采样 slots")
    plan = assemble_plan(
        keyword=req.keyword,
        template=template,
        index=index,
        registry=registry,
        seed=req.seed,
        user_config=req.user_config or {},
    )

    _emit("组装 prompt")
    draft = _compose_draft_with_framework(plan, template, req)

    if req.draft_only:
        # Two-phase UI flow: stop here so the user can review / edit the draft
        # before the LLM is spent on polishing it. ``final_text`` is blank and
        # nothing is written to disk.
        return GenerateResult(
            markdown_path="",
            assembly_json_path="",
            plan=plan,
            final_text="",
        )

    system, user = build_prompt(PromptInputs(
        template_system_prompt=template.system_prompt_default,
        user_skill_prompt=req.user_skill_prompt,
        seo=template.seo_defaults,
        keyword=req.keyword,
        draft=draft,
    ))

    _emit("调用 LLM")
    final_text = req.llm_client.complete(system=system, user=user)

    _emit("导出")
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
    return GenerateResult(
        markdown_path=paths["markdown"],
        assembly_json_path=paths["assembly_json"],
        plan=plan,
        final_text=final_text,
    )
