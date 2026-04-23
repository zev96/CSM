"""Serial batch generation runner (no Qt deps)."""
from __future__ import annotations
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..vault.scanner import scan_vault
from ..vault.brand_registry import build_brand_registry
from ..template.loader import load_template
from ..assembler.constraints import assemble_plan
from ..assembler.render import compose_draft
from ..llm.client import LLMClient
from ..llm.prompts import build_prompt, PromptInputs
from ..export.markdown import export_article
from .report import BatchReport, BatchItem, write_report


def _dedup_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        k = k.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def run_batch(
    keywords: list[str],
    template_path: Path,
    vault_root: Path,
    out_dir: Path,
    llm_client: LLMClient,
    seed: int,
    on_item_started: Callable[[int, str], None] = lambda i, kw: None,
    on_item_finished: Callable[[BatchItem], None] = lambda item: None,
    should_cancel: Callable[[], bool] = lambda: False,
    skill_dir: Path | None = None,
) -> BatchReport:
    cleaned = _dedup_keywords(keywords)
    batch_id = out_dir.name
    report_path = out_dir / "batch-report.json"
    report = BatchReport(
        batch_id=batch_id,
        batch_dir=str(out_dir),
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=None,
        template_path=str(template_path),
        vault_root=str(vault_root),
        seed=seed,
        total=len(cleaned),
    )
    write_report(report, report_path)

    index = scan_vault(vault_root)
    registry = build_brand_registry(vault_root)
    template = load_template(template_path)

    # Resolve default skill once per batch. Missing file → empty system prompt
    # (same behavior as pre-migration when a template lacked system_prompt_default).
    user_skill_prompt: str | None = None
    if template.default_skill_id and skill_dir is not None:
        skill_path = Path(skill_dir) / f"{template.default_skill_id}.md"
        if skill_path.is_file():
            user_skill_prompt = skill_path.read_text(encoding="utf-8")

    for i, keyword in enumerate(cleaned, start=1):
        if should_cancel():
            break
        on_item_started(i, keyword)
        started = time.monotonic()
        try:
            plan = assemble_plan(
                keyword=keyword, template=template,
                index=index, registry=registry,
                seed=seed, user_config={},
            )
            draft = compose_draft(plan)
            system, user = build_prompt(PromptInputs(
                user_skill_prompt=user_skill_prompt,
                keyword=keyword,
                draft=draft,
            ))
            final_text = llm_client.complete(system=system, user=user)
            paths = export_article(
                out_dir=out_dir,
                keyword=keyword,
                final_text=final_text,
                plan=plan,
                prompt_snapshot={
                    "system": system, "user": user,
                    "provider": type(llm_client).__name__,
                },
            )
            item = BatchItem(
                index=i, keyword=keyword, status="success",
                markdown_path=paths["markdown"],
                assembly_json_path=paths["assembly_json"],
                duration_seconds=round(time.monotonic() - started, 3),
            )
        except Exception as exc:  # noqa: BLE001 — per-item boundary
            err_msg = str(exc).splitlines()[0] if str(exc) else ""
            item = BatchItem(
                index=i, keyword=keyword, status="failed",
                error_type=type(exc).__name__,
                error_message=err_msg,
                duration_seconds=round(time.monotonic() - started, 3),
            )
        report.items.append(item)
        write_report(report, report_path)
        on_item_finished(item)

    report.finished_at = datetime.now().isoformat(timespec="seconds")
    write_report(report, report_path)
    return report
