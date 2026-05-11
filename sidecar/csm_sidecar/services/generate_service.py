"""Article generation orchestration.

We **don't** call :func:`csm_core.pipeline.generate` because its tail end
references ``paths["assembly_json"]`` which no longer exists in the
current ``export_article`` (the snapshot sidecar was dropped — see
``csm_core/export/markdown.py``). Rather than touch csm_core to fix that
unrelated issue, we compose csm_core's individual stage functions here:
identical orchestration, no broken hand-off.

Stages are emitted to the EventBus so the SSE endpoint can stream them.
The job is queued onto a ThreadPoolExecutor — pipeline functions are
sync/blocking (vault scan + LLM call) and we want them off the FastAPI
event loop.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from csm_core.assembler.constraints import assemble_plan
from csm_core.assembler.render import compose_draft
from csm_core.export.markdown import export_article
from csm_core.llm.client import LLMClient
from csm_core.llm.prompts import PromptInputs, build_prompt
from csm_core.template.loader import load_template
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault.scanner import scan_vault

from ..event_bus import bus
from . import (
    assembler_service,
    config_service,
    llm_factory,
    skills_service,
    templates_service,
)

logger = logging.getLogger(__name__)


@dataclass
class GenerateRequest:
    keyword: str
    template_id: str
    skill_id: str | None = None
    seed: int = 0
    draft_only: bool = False
    core_keyword: str | None = None
    provider: str | None = None
    model: str | None = None
    user_config: dict[str, int] | None = None


# Pool sized so a typical desktop can run a generate + a batch + a polish
# concurrently without thrashing. Provider HTTP clients have their own
# retry; we don't want unlimited fan-out.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="generate")
_lock = threading.Lock()


def submit(req: GenerateRequest) -> str:
    """Kick off a job, return the ``job_id`` to subscribe via SSE."""
    job_id = bus.create_job()
    _executor.submit(_run_job, job_id, req)
    return job_id


def _run_job(job_id: str, req: GenerateRequest) -> None:
    """Worker body. Push events at every checkpoint."""
    try:
        # Resolve all paths/clients up-front — fail fast and cleanly if
        # config is incomplete, rather than half-way through scanning.
        cfg = config_service.load()
        if not cfg.vault_root:
            raise ValueError("AppConfig.vault_root is unset")
        if not cfg.out_dir:
            raise ValueError("AppConfig.out_dir is unset")
        vault_root = Path(cfg.vault_root)
        out_dir = Path(cfg.out_dir)

        tpl_path = templates_service.resolve_dir() / f"{req.template_id}.json"
        if not tpl_path.exists():
            raise FileNotFoundError(f"template not found: {req.template_id}")

        skill_prompt: str | None = None
        if req.skill_id:
            skill = skills_service.get_skill(
                Path(cfg.skill_dir) if cfg.skill_dir else None,
                req.skill_id,
            )
            if skill is None:
                raise FileNotFoundError(f"skill not found: {req.skill_id}")
            skill_prompt = skill.body

        bus.publish(job_id, "stage", stage="扫描资料库", index=0, total=6)
        index = scan_vault(vault_root)
        registry = build_brand_registry(vault_root)

        bus.publish(job_id, "stage", stage="加载模板", index=1, total=6)
        template = load_template(tpl_path)

        bus.publish(job_id, "stage", stage="采样 blocks", index=2, total=6)
        plan = assemble_plan(
            keyword=req.keyword,
            template=template,
            index=index,
            registry=registry,
            seed=req.seed,
            user_config=req.user_config or {},
            core_keyword=req.core_keyword,
        )
        # Stash the plan so subsequent /api/assembler/reroll calls can
        # operate on it without re-scanning the vault.
        assembler_service.cache_plan(
            job_id, plan, template_id=req.template_id, seed=req.seed,
        )

        bus.publish(job_id, "stage", stage="组装 prompt", index=3, total=6)
        draft = compose_draft(plan)

        if req.draft_only:
            bus.finish(
                job_id,
                draft=draft,
                plan=_plan_to_dict(plan),
                document=None,
            )
            return

        client: LLMClient = llm_factory.build_client(
            provider=req.provider, model=req.model,
        )
        system, user = build_prompt(PromptInputs(
            user_skill_prompt=skill_prompt,
            keyword=req.keyword,
            draft=draft,
        ))

        bus.publish(job_id, "stage", stage="调用 LLM", index=4, total=6)
        final_text = client.complete(system=system, user=user)

        bus.publish(job_id, "stage", stage="导出", index=5, total=6)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = export_article(
            out_dir=out_dir,
            keyword=req.keyword,
            final_text=final_text,
            plan=plan,
            fmt=cfg.export_format,
        )

        bus.finish(
            job_id,
            document=paths["document"],
            format=paths["format"],
            title=paths["title"],
            plan=_plan_to_dict(plan),
            final_text=final_text,
        )
    except Exception as e:
        logger.exception("generate job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")


def _plan_to_dict(plan: Any) -> dict[str, Any]:
    """Best-effort conversion of AssemblyPlan to JSON-friendly dict."""
    if hasattr(plan, "model_dump"):
        return plan.model_dump()
    if hasattr(plan, "__dataclass_fields__"):
        return asdict(plan)
    return dict(getattr(plan, "__dict__", {}) or {})
