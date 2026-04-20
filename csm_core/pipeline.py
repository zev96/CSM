"""End-to-end orchestration: keyword + template → article."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .vault.scanner import scan_vault
from .vault.brand_registry import build_brand_registry
from .template.loader import load_template
from .assembler.constraints import assemble_plan
from .assembler.plan import AssemblyPlan
from .llm.client import LLMClient
from .llm.prompts import build_prompt, PromptInputs
from .export.markdown import export_article


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


@dataclass
class GenerateResult:
    markdown_path: str
    assembly_json_path: str
    plan: AssemblyPlan
    final_text: str


def _render_draft(plan: AssemblyPlan) -> str:
    parts: list[str] = []
    for slot in plan.slots:
        if not slot.picks:
            continue
        parts.append("\n\n".join(p.text for p in slot.picks))
    return "\n\n".join(parts)


def generate(req: GenerateRequest) -> GenerateResult:
    index = scan_vault(req.vault_root)
    registry = build_brand_registry(req.vault_root)
    template = load_template(req.template_path)

    plan = assemble_plan(
        keyword=req.keyword,
        template=template,
        index=index,
        registry=registry,
        seed=req.seed,
        user_config=req.user_config or {},
    )

    draft = _render_draft(plan)

    system, user = build_prompt(PromptInputs(
        template_system_prompt=template.system_prompt_default,
        user_skill_prompt=req.user_skill_prompt,
        seo=template.seo_defaults,
        keyword=req.keyword,
        draft=draft,
    ))
    final_text = req.llm_client.complete(system=system, user=user)

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
