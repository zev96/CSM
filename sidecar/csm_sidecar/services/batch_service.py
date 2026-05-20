"""Batch generation orchestration.

We don't call :func:`csm_core.batch.runner.run_batch` directly because its
tail end references ``paths["markdown"]`` / ``paths["assembly_json"]`` —
keys that no longer exist in the current ``export_article`` (snapshot
sidecar was dropped). The same stage composition is replayed here with
the correct hand-off, mirroring the Group 2 generate_service pattern.

Why hold state in-memory in addition to publishing SSE
------------------------------------------------------
The SSE bus is the *push* channel for live UI; the in-memory state map
is the *pull* channel for ``GET /api/batch/{job_id}`` (refresh, late
join, post-mortem inspection). Without it a UI reload would lose all
progress because EventBus reaps streams once consumed.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from csm_core.assembler.constraints import assemble_plan
from csm_core.assembler.render import compose_draft
from csm_core.export.markdown import export_article
from csm_core.llm.client import LLMClient
from csm_core.llm.prompts import PromptInputs, build_prompt
from csm_core.template.loader import load_template
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault.scanner import scan_vault

from ..event_bus import bus
from . import config_service, llm_factory, skills_service, templates_service

logger = logging.getLogger(__name__)


ItemStatus = Literal["queued", "running", "success", "failed", "cancelled"]


@dataclass
class BatchItemState:
    index: int
    keyword: str
    status: ItemStatus = "queued"
    duration_seconds: float = 0.0
    document: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class BatchState:
    job_id: str
    keywords: list[str]
    template_id: str
    skill_id: str | None
    provider: str | None
    model: str | None
    seed: int
    started_at: str
    finished_at: str | None = None
    cancel_requested: bool = False
    items: list[BatchItemState] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "keywords": self.keywords,
            "template_id": self.template_id,
            "skill_id": self.skill_id,
            "provider": self.provider,
            "model": self.model,
            "seed": self.seed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
            "items": [vars(it) for it in self.items],
        }


@dataclass
class BatchRequest:
    keywords: list[str]
    template_id: str
    skill_id: str | None = None
    seed: int = 0
    provider: str | None = None
    model: str | None = None


# Process-global state. Keyed by job_id. Lock guards both dict mutation
# and per-state field reads (cancel_requested) since worker thread reads
# while route handlers write.
#
# OrderedDict + MAX_CACHE so a long-running sidecar that's seen hundreds
# of batches doesn't keep every BatchState (which holds a per-item list)
# in memory forever. Eviction only drops *finished* entries — a running
# batch is never silently forgotten.
_states: "OrderedDict[str, BatchState]" = OrderedDict()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="batch")
MAX_CACHE = 50


def submit(req: BatchRequest) -> str:
    """Create job_id, register state, kick off worker."""
    keywords = _dedup_keywords(req.keywords)
    if not keywords:
        raise ValueError("keywords list is empty after dedup")

    job_id = uuid.uuid4().hex
    bus.create_job(job_id)
    state = BatchState(
        job_id=job_id,
        keywords=keywords,
        template_id=req.template_id,
        skill_id=req.skill_id,
        provider=req.provider,
        model=req.model,
        seed=req.seed,
        started_at=datetime.now().isoformat(timespec="seconds"),
        items=[BatchItemState(index=i, keyword=kw) for i, kw in enumerate(keywords, start=1)],
    )
    with _lock:
        _states[job_id] = state
        _evict_finished_overflow_unlocked()
    _executor.submit(_run_job, job_id)
    return job_id


def get_state(job_id: str) -> BatchState | None:
    with _lock:
        return _states.get(job_id)


def request_cancel(job_id: str) -> bool:
    """Return True if the job exists and was newly marked for cancel."""
    with _lock:
        st = _states.get(job_id)
        if st is None:
            return False
        if st.cancel_requested or st.finished_at is not None:
            return False
        st.cancel_requested = True
    bus.publish(job_id, "cancel_requested")
    return True


def _dedup_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        k = (k or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _run_job(job_id: str) -> None:
    """Worker body. Mirrors csm_core.batch.runner stage-by-stage but with
    the correct ``paths["document"]`` hand-off."""
    state = _states[job_id]
    try:
        cfg = config_service.load()
        if not cfg.vault_root:
            raise ValueError("AppConfig.vault_root is unset")
        if not cfg.out_dir:
            raise ValueError("AppConfig.out_dir is unset")
        vault_root = Path(cfg.vault_root)
        # Each batch lives in its own subdir so multiple batches don't
        # fight over the MMDD-N filename slots.
        out_dir = Path(cfg.out_dir) / f"batch-{job_id[:8]}"
        out_dir.mkdir(parents=True, exist_ok=True)

        tpl_path = templates_service.resolve_dir() / f"{state.template_id}.json"
        if not tpl_path.exists():
            raise FileNotFoundError(f"template not found: {state.template_id}")

        skill_prompt: str | None = None
        if state.skill_id:
            skill = skills_service.get_skill(
                Path(cfg.skill_dir) if cfg.skill_dir else None,
                state.skill_id,
            )
            if skill is None:
                raise FileNotFoundError(f"skill not found: {state.skill_id}")
            skill_prompt = skill.body

        client: LLMClient = llm_factory.build_client(
            provider=state.provider, model=state.model,
        )

        bus.publish(
            job_id, "started",
            total=len(state.keywords), out_dir=str(out_dir),
        )

        # One-time heavy reads — done outside the per-keyword loop.
        index = scan_vault(vault_root)
        registry = build_brand_registry(vault_root)
        template = load_template(tpl_path)
        # If no per-batch skill picked, fall back to template default
        # (mirrors run_batch behavior).
        if skill_prompt is None and template.default_skill_id and cfg.skill_dir:
            tpl_skill = skills_service.get_skill(
                Path(cfg.skill_dir), template.default_skill_id,
            )
            if tpl_skill is not None:
                skill_prompt = tpl_skill.body

        for item in state.items:
            with _lock:
                if state.cancel_requested:
                    break
            item.status = "running"
            bus.publish(
                job_id, "item_started",
                index=item.index, keyword=item.keyword,
            )
            t0 = time.monotonic()
            try:
                plan = assemble_plan(
                    keyword=item.keyword, template=template,
                    index=index, registry=registry,
                    seed=state.seed, user_config={},
                )
                draft = compose_draft(plan)
                system, user = build_prompt(PromptInputs(
                    user_skill_prompt=skill_prompt,
                    keyword=item.keyword, draft=draft,
                ))
                final_text = client.complete(system=system, user=user)
                paths = export_article(
                    out_dir=out_dir,
                    keyword=item.keyword,
                    final_text=final_text,
                    plan=plan,
                    fmt=cfg.export_format,
                )
                item.document = paths["document"]
                item.status = "success"
            except Exception as exc:  # noqa: BLE001 — per-item boundary
                logger.exception("batch %s item %d failed", job_id, item.index)
                item.status = "failed"
                item.error_type = type(exc).__name__
                err_text = str(exc).splitlines()[0] if str(exc) else ""
                item.error_message = err_text
            finally:
                item.duration_seconds = round(time.monotonic() - t0, 3)
                bus.publish(
                    job_id, "item_finished",
                    index=item.index,
                    keyword=item.keyword,
                    status=item.status,
                    duration_seconds=item.duration_seconds,
                    document=item.document,
                    error_type=item.error_type,
                    error_message=item.error_message,
                )

        # Anything still queued at the end was cancelled mid-run.
        for it in state.items:
            if it.status == "queued":
                it.status = "cancelled"

        with _lock:
            state.finished_at = datetime.now().isoformat(timespec="seconds")

        summary = _summary(state)
        bus.finish(job_id, **summary)
    except Exception as e:
        logger.exception("batch %s crashed", job_id)
        with _lock:
            state.finished_at = datetime.now().isoformat(timespec="seconds")
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")


def _summary(state: BatchState) -> dict:
    by_status: dict[str, int] = {}
    for it in state.items:
        by_status[it.status] = by_status.get(it.status, 0) + 1
    total_duration = sum(it.duration_seconds for it in state.items)
    return {
        "total": len(state.items),
        "by_status": by_status,
        "total_duration_seconds": round(total_duration, 3),
    }


def _evict_finished_overflow_unlocked() -> None:
    """Drop oldest *finished* batches when ``_states`` exceeds ``MAX_CACHE``.

    Must be called with ``_lock`` held. Walks insertion order (oldest first)
    and pops entries whose ``finished_at`` is set, until we're back under
    capacity. A running batch (``finished_at is None``) is never evicted —
    we don't want to forget a job a user is still watching, even if it's
    been queued for a long time.

    Pathological case: if all 50 slots are filled with running batches
    (max_workers=2 makes this implausible — submit blocks before that),
    eviction is a no-op and the cache grows past MAX_CACHE until something
    finishes. That's the right trade-off.
    """
    if len(_states) <= MAX_CACHE:
        return
    overflow = len(_states) - MAX_CACHE
    to_drop: list[str] = []
    for jid, st in _states.items():
        if len(to_drop) >= overflow:
            break
        if st.finished_at is not None:
            to_drop.append(jid)
    for jid in to_drop:
        del _states[jid]
    if to_drop:
        logger.debug("batch_service evicted %d finished states", len(to_drop))


def reset_for_test() -> None:
    """Test-only — wipe the state cache between tests."""
    with _lock:
        _states.clear()
