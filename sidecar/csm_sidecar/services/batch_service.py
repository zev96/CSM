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
import re
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
from csm_core.brand_memory.inject import build_whitelist, render_brand_facts, resolve_scopes
from csm_core.export.markdown import export_article
from csm_core.factcheck import check_facts
from csm_core.factcheck.completeness import check_completeness
from csm_core.lint import build_report as lint_report_for
from csm_core.lint import build_rules
from csm_core.llm import pricing
from csm_core.llm.client import LLMClient
from csm_core.scoring import score_article
from csm_core.template.loader import load_template
from csm_core.vault.brand_registry import build_brand_registry

from ..event_bus import bus
from . import chain_service, config_service, llm_factory, skills_service, templates_service, vault_service

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
    score: float | None = None
    score_parts: list[dict] = field(default_factory=list)      # top3 扣分明细
    candidate_scores: list[float] = field(default_factory=list)
    factcheck_violations: int = 0


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
    skill_chain: list[str] | None = None
    candidates: int = 1
    contract_mode: str | None = None

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
            "skill_chain": self.skill_chain,
            "candidates": self.candidates,
            "contract_mode": self.contract_mode,
        }


@dataclass
class BatchRequest:
    keywords: list[str]
    template_id: str
    skill_id: str | None = None
    seed: int = 0
    provider: str | None = None
    model: str | None = None
    skill_chain: list[str] | None = None
    candidates: int = 1
    contract_mode: str | None = None


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
# Lazy-init: shutdown() nulls the pool, the next submit() lazy-recreates.
# See generate_service for the rationale (lifespan cycle vs test reuse).
_executor: ThreadPoolExecutor | None = None
MAX_CACHE = 50


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="batch")
    return _executor


def shutdown() -> None:
    """Idempotent shutdown — called from sidecar lifespan finally."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


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
        skill_chain=req.skill_chain,
        candidates=max(1, min(3, req.candidates)),
        contract_mode=req.contract_mode,
    )
    with _lock:
        _states[job_id] = state
        _evict_finished_overflow_unlocked()
    _get_executor().submit(_run_job, job_id)
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


def _safe_stem(s: str) -> str:
    """Windows 安全文件名片段：非法字符与空白 → _，截 20 字。"""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s)[:20] or "kw"


def _save_candidate(out_dir: Path, item: BatchItemState, cand: dict, k: int) -> None:
    """落选稿存 candidates/ 备查（纯 md dump，不走 export_article 的 MMDD-N 槽位）。

    文件名含候选序 c{k} + 一位小数分 —— 同词多落选稿同分也不互相覆盖（终审 Minor）。
    mkdir 也在 OSError 守卫内：candidates/ 不可建时降级为日志，绝不把已成优胜拖成 failed。"""
    score = cand["score_report"].total
    try:
        cdir = out_dir / "candidates"
        cdir.mkdir(exist_ok=True)
        path = cdir / f"{item.index:02d}-{_safe_stem(item.keyword)}-c{k}-{score:.1f}分.md"
        path.write_text(cand["final_text"], encoding="utf-8")
    except OSError:
        logger.warning("batch 落选稿写入失败: item=%d c%d", item.index, k, exc_info=True)


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
        index = vault_service.get(vault_root)
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

        # 链 steps：skill_chain 优先；None 退化 [skill_id]（找不到已在上面 fail-fast）；
        # 两者皆空且模板有默认 skill → 单步默认链（沿用今天回退语义）。
        chain_steps: list[chain_service.ChainStepInput] = []
        if state.skill_chain:
            sdir = Path(cfg.skill_dir) if cfg.skill_dir else None
            for sid in state.skill_chain:
                sk = skills_service.get_skill(sdir, sid)
                if sk is None:
                    logger.warning("batch skill_chain: 跳过失效 skill %s", sid)
                    continue
                chain_steps.append(chain_service.ChainStepInput(
                    skill_id=sid, role=sk.role, name=sk.name, body=sk.body))
        elif skill_prompt is not None:
            chain_steps = [chain_service.ChainStepInput(
                skill_id=state.skill_id, role="persona", name="", body=skill_prompt)]
        effective_contract = state.contract_mode or cfg.contract.mode
        lint_rules = build_rules(cfg.lint)
        state_cost_acc: list[list[dict]] = []    # 每链的 pass_dicts，done 时求 total_cost

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
                best: dict | None = None       # {final_text, plan, score_report, fc_n, k}
                cand_scores: list[float] = []
                last_exc: Exception | None = None   # 全候选失败时把真因抛给 per-item except
                was_cancelled = False
                total_cost_acc = state_cost_acc   # 外层累计器（每链 pass_dicts）
                for k in range(1, state.candidates + 1):
                    with _lock:
                        if state.cancel_requested:
                            was_cancelled = True
                            break
                    # 候选级故障隔离：单候选失败只丢自己，不弃已有优胜、不拖垮整词。
                    try:
                        plan = assemble_plan(
                            keyword=item.keyword, template=template,
                            index=index, registry=registry,
                            seed=state.seed + (k - 1) * 1000, user_config={},
                            # 候选素材各随机（seed 间隔 1000），但结构版本统一
                            # 走批次基准 seed：评分是绝对次数扣分制、不按篇幅
                            # 归一，候选落在不同结构上会让长版本被系统性打低分，
                            # best-of-K 就退化成「总选最短的版本」。
                            version_seed=state.seed,
                        )
                        draft = compose_draft(plan)
                        # 注入（与 finalize_draft 同条件：inject 或 factcheck 开才解析 scopes）
                        scopes: list = []
                        brand_facts = None
                        if cfg.brand_memory.inject or cfg.brand_memory.factcheck:
                            scopes = resolve_scopes(
                                plan, index, registry,
                                own_brands=set(cfg.brand_memory.own_brands),
                                category=template.product)
                            if scopes and cfg.brand_memory.inject:
                                brand_facts = render_brand_facts(
                                    scopes,
                                    variant_cap=cfg.brand_memory.inject_variant_cap,
                                    endorsement_cap=cfg.brand_memory.inject_endorsement_cap)
                        chain_state = chain_service.run_chain(
                            f"{job_id}:{item.index}:{k}", chain_steps,
                            draft=draft, keyword=item.keyword, title=None,
                            angle_directive=None, brand_facts=brand_facts,
                            provider=state.provider, model=state.model,
                            client=client, contract_mode=effective_contract,
                            cache=False)
                        final_k = chain_state.final_text
                        pass_dicts = [p.to_dict() for p in chain_state.passes]
                        total_cost_acc.append(pass_dicts)
                        # 核对信号（计数不拦）
                        fc_n = 0
                        if cfg.brand_memory.factcheck and scopes:
                            sources = [draft] + ([brand_facts] if brand_facts else [])
                            wl = build_whitelist(scopes, source_texts=sources)
                            fc_n = len(check_facts(
                                final_k, allowed_numbers=wl.numbers,
                                allowed_certs=wl.certs).violations)
                        comp_n = 0
                        if effective_contract == "aggressive" and scopes:
                            comp_n = len(check_completeness(draft, final_k, scopes).missing)
                        report = score_article(
                            final_k, lint_report=lint_report_for(final_k, lint_rules),
                            factcheck_violations=fc_n, completeness_missing=comp_n,
                            config=cfg.scoring)
                    except Exception as cand_exc:  # noqa: BLE001 — 候选级边界
                        logger.warning(
                            "batch %s item %d candidate %d failed",
                            job_id, item.index, k, exc_info=True)
                        last_exc = cand_exc
                        continue
                    cand_scores.append(report.total)
                    if best is None or report.total > best["score_report"].total:
                        if best is not None:
                            # 旧优胜者降级为落选稿，带自己的候选序 best["k"]。
                            _save_candidate(out_dir, item, best, best["k"])
                        best = {"final_text": final_k, "plan": plan,
                                "score_report": report, "fc_n": fc_n, "k": k}
                    else:
                        _save_candidate(out_dir, item, {
                            "final_text": final_k, "score_report": report}, k)
                if best is None:
                    if was_cancelled:
                        # 用户取消且零成稿 —— 是取消不是失败（error_* 留空）。
                        item.status = "cancelled"
                        continue  # finally 仍发 item_finished（status=cancelled）
                    # 全候选失败：把真实的最后一个异常抛给 per-item except（error_* 取真因）。
                    raise last_exc if last_exc is not None else RuntimeError(
                        "batch item produced no candidate")
                paths = export_article(
                    out_dir=out_dir, keyword=item.keyword,
                    final_text=best["final_text"], plan=best["plan"],
                    fmt=cfg.export_format)
                item.document = paths["document"]
                item.score = best["score_report"].total
                item.score_parts = [p.model_dump() for p in best["score_report"].parts[:3]]
                item.candidate_scores = cand_scores
                item.factcheck_violations = best["fc_n"]
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
                    score=item.score, score_parts=item.score_parts,
                    candidate_scores=item.candidate_scores,
                    factcheck_violations=item.factcheck_violations,
                )

        # Anything still queued at the end was cancelled mid-run.
        for it in state.items:
            if it.status == "queued":
                it.status = "cancelled"

        with _lock:
            state.finished_at = datetime.now().isoformat(timespec="seconds")

        summary = _summary(state)
        model_name = state.model or (
            cfg.default_model.get(state.provider or cfg.default_provider or "")
            if (state.provider or cfg.default_provider) else None)
        agg = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "currency": "CNY"}
        any_cost = False
        for pass_dicts in state_cost_acc:
            c = pricing.chain_cost(pass_dicts, model_name, cfg.pricing)
            agg["input_tokens"] += c["input_tokens"]
            agg["output_tokens"] += c["output_tokens"]
            if c["cost"] is not None:
                agg["cost"] += c["cost"]; any_cost = True
        if not any_cost:
            agg["cost"] = None
        summary["total_cost"] = agg
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
