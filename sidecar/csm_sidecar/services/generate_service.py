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

from csm_core.angle import Angle, effective_sellpoints, render_angle_directive
from csm_core.assembler.constraints import assemble_plan
from csm_core.assembler.render import compose_draft
from csm_core.export.markdown import export_article
from csm_core.template.loader import load_template
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.inject import build_whitelist, render_brand_facts, resolve_scopes
from csm_core.factcheck import check_facts

from ..event_bus import bus
from . import (
    assembler_service,
    chain_service,
    config_service,
    factcheck_service,
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
    # Phase 2a: 标题领衔 + 角度选材。两者都空 = 今天行为（零回归）。
    title: str | None = None
    angle: Angle | None = None
    # Phase 2b: skill 链多-pass（人设→去AI味→平台适配）。空 = 退回单 skill_id
    # 1 步链 = 今天行为（零回归）。
    skill_chain: list[str] | None = None


# Pool sized so a typical desktop can run a generate + a batch + a polish
# concurrently without thrashing. Provider HTTP clients have their own
# retry; we don't want unlimited fan-out.
#
# Lazy-init: created on first submit() and nulled by shutdown(). Lifespan
# calls shutdown() in its finally block; the next submit() (in production
# this is "never" because the process exits; in tests it's the next
# TestClient iteration) re-creates the pool cleanly.
_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()

# ── 协作式取消 ───────────────────────────────────────────────────────
# request_cancel 只对仍在 _live 里的 job 生效；_run_job 在各 stage 检查点
# （含调用 LLM 前）调 _checkpoint，命中则以 error 事件收尾（EventBus 只认
# done/error 终结流），payload 带 cancelled=True 让前端静默处理。
# LLM 调用本身不可中断；「导出」阶段不设检查点 —— LLM 已经花了钱，
# 落盘比丢弃好。与 batch/monitor 的协作式语义一致。
_live: set[str] = set()
_cancelled: set[str] = set()
_state_lock = threading.Lock()


class _CancelledGenerate(Exception):
    """Raised at a checkpoint when the user requested cancel."""


def request_cancel(job_id: str) -> bool:
    """Return True if the job is live and was newly marked for cancel."""
    with _state_lock:
        if job_id not in _live or job_id in _cancelled:
            return False
        _cancelled.add(job_id)
    bus.publish(job_id, "cancel_requested")
    return True


def _checkpoint(job_id: str) -> None:
    with _state_lock:
        hit = job_id in _cancelled
    if hit:
        raise _CancelledGenerate()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="generate")
    return _executor


def shutdown() -> None:
    """Idempotent shutdown. Cancels queued work and nulls the pool so a
    subsequent submit() can lazy-recreate. ``wait=False`` because the
    sidecar process is about to exit; in-flight jobs die with it."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def submit(req: GenerateRequest) -> str:
    """Kick off a job, return the ``job_id`` to subscribe via SSE."""
    job_id = bus.create_job()
    with _state_lock:
        _live.add(job_id)
    _get_executor().submit(_run_job, job_id, req)
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

        # skill 链解析提前到此处 —— 与今天的早期 skill-load 一样 fail-fast：
        # 单 skill_id（无 chain）找不到仍抛 FileNotFoundError（零回归）。
        chain_steps = _resolve_chain(req, cfg)

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="扫描资料库", index=0, total=6)
        index = scan_vault(vault_root)
        registry = build_brand_registry(vault_root)

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="加载模板", index=1, total=6)
        template = load_template(tpl_path)

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="采样 blocks", index=2, total=6)
        plan = assemble_plan(
            keyword=req.keyword,
            template=template,
            index=index,
            registry=registry,
            seed=req.seed,
            user_config=req.user_config or {},
            core_keyword=req.core_keyword,
            angle=req.angle,
        )
        # Stash the plan so subsequent /api/assembler/reroll calls can
        # operate on it without re-scanning the vault.
        assembler_service.cache_plan(
            job_id, plan, template_id=req.template_id, seed=req.seed,
        )

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="组装 prompt", index=3, total=6)
        draft = compose_draft(plan)

        # 组装阶段产出的 plan + draft 立即推给前端 —— 这样用户在 LLM 阶段
        # 还在跑时就能在 "组装" / "初稿" tab 里看到内容，而不是等到整个 job
        # done 才一次性显示（组装本身不依赖 LLM，没必要让 UI 陪等）。
        bus.publish(
            job_id, "assembly",
            plan=_plan_to_dict(plan),
            draft=draft,
        )

        if req.draft_only:
            bus.finish(
                job_id,
                draft=draft,
                plan=_plan_to_dict(plan),
                document=None,
            )
            return

        # Plan 3: 注入型号记忆 + 事实核对作用域。两个 flag 都关 = 跳过。
        cfg_bm = cfg.brand_memory
        scopes: list = []
        brand_facts: str | None = None
        if cfg_bm.inject or cfg_bm.factcheck:
            scopes = resolve_scopes(
                plan, index, registry,
                own_brands=set(cfg_bm.own_brands),
                category=template.product,
            )
            if scopes:
                brand_facts = render_brand_facts(
                    scopes,
                    variant_cap=cfg_bm.inject_variant_cap,
                    endorsement_cap=cfg_bm.inject_endorsement_cap,
                    sellpoints=effective_sellpoints(req.angle),
                )

        # Phase 2b: 单次 build_prompt+complete 升级为 skill 链多-pass。
        # step0 = 组装 pass（build_prompt：毛坯+事实+角度+标题，与今天一致）；
        # step1+ = 精修 pass（build_refine_prompt：上段输出+skill）。逐 pass 经
        # SSE 推给前端，链状态按 job_id 缓存供 /api/chain/rerun 重跑。单步链
        # （无 skill_chain）的 step0 入参与今天 build_prompt 字节级一致（零回归）。
        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="skill 链润色", index=4, total=6)
        state = chain_service.run_chain(
            job_id, chain_steps,
            draft=draft,
            keyword=req.keyword,
            title=req.title,
            angle_directive=render_angle_directive(req.angle),
            brand_facts=brand_facts if cfg_bm.inject else None,
            provider=req.provider, model=req.model,
            checkpoint=lambda: _checkpoint(job_id),
            on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()),
        )
        final_text = state.final_text
        passes = [p.to_dict() for p in state.passes]

        # 导出前硬门禁：命中越界则缓存待导出 + done(blocked)，不导出。
        if _maybe_block_for_factcheck(
            job_id, final_text=final_text, scopes=scopes, draft=draft,
            brand_facts=brand_facts if cfg_bm.inject else None,
            title=req.title, cfg=cfg, plan=plan, out_dir=out_dir,
            passes=passes,
        ):
            return

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
            draft=draft,
            final_text=final_text,
            passes=passes,
        )
    except _CancelledGenerate:
        logger.info("generate job %s cancelled by user", job_id)
        bus.fail(job_id, error="cancelled", cancelled=True)
    except Exception as e:
        logger.exception("generate job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    finally:
        with _state_lock:
            _live.discard(job_id)
            _cancelled.discard(job_id)


def _resolve_chain(req: GenerateRequest, cfg) -> list[chain_service.ChainStepInput]:
    """把 req 解析成链 steps（每个 step 带 skill 的 role/name/body）。

    零回归边界：
    - 无 skill_chain 时退回单 skill_id（[skill_id] if skill_id else []）；单
      skill_id 给了但找不到 → **抛 FileNotFoundError**（与今天早期 skill-load
      一致，不静默成空链）。
    - 多条 skill_chain 里某条失效 → 跳过 + warning，链继续（其它步仍跑）。"""
    sdir = Path(cfg.skill_dir) if cfg.skill_dir else None
    if req.skill_chain is None:
        # 单 skill_id 路径：保留今天的「找不到即抛」契约。
        if not req.skill_id:
            return []
        skill = skills_service.get_skill(sdir, req.skill_id)
        if skill is None:
            raise FileNotFoundError(f"skill not found: {req.skill_id}")
        return [chain_service.ChainStepInput(
            skill_id=req.skill_id, role=skill.role, name=skill.name, body=skill.body)]
    # 多步链路径：单条失效跳过 + warning（不中断整条链）。
    steps: list[chain_service.ChainStepInput] = []
    for sid in req.skill_chain:
        skill = skills_service.get_skill(sdir, sid)
        if skill is None:
            logger.warning("skill_chain: 跳过失效 skill %s", sid)
            continue
        steps.append(chain_service.ChainStepInput(
            skill_id=sid, role=skill.role, name=skill.name, body=skill.body))
    return steps


def _maybe_block_for_factcheck(
    job_id: str, *, final_text: str, scopes: list, draft: str,
    brand_facts: str | None, title: str | None = None, cfg, plan, out_dir: Path,
    passes: list[dict[str, Any]] | None = None,
) -> bool:
    """导出前事实核对。命中越界 → 缓存待导出 + 以 done(blocked) 收尾、返回
    True（调用方须在导出前停下）。核对关 / 无型号 / 成稿干净 → False。

    白名单源 = 毛坯文 + 标题（若有）+ 已注入品牌事实（若有）：标题往往
    自带数字（如「220AW 实测」），不纳入会被事实核对误判越界。

    blocked done 也带 passes（链每段输出）：前端被拦时仍能逐 pass 预览/重跑。"""
    if not cfg.brand_memory.factcheck or not scopes:
        return False
    sources = [draft] + ([title] if title else []) + ([brand_facts] if brand_facts else [])
    wl = build_whitelist(scopes, source_texts=sources)
    report = check_facts(
        final_text, allowed_numbers=wl.numbers, allowed_certs=wl.certs,
    )
    if report.ok:
        return False
    factcheck_service.cache_pending(
        job_id, plan=plan, out_dir=out_dir, keyword=plan.keyword,
        fmt=cfg.export_format, allowed_numbers=wl.numbers, allowed_certs=wl.certs,
    )
    bus.finish(
        job_id, document=None, plan=_plan_to_dict(plan), draft=draft,
        final_text=final_text,
        passes=passes or [],
        factcheck={
            "blocked": True,
            "violations": [v.model_dump() for v in report.violations],
        },
    )
    return True


def _plan_to_dict(plan: Any) -> dict[str, Any]:
    """Best-effort conversion of AssemblyPlan to JSON-friendly dict."""
    if hasattr(plan, "model_dump"):
        return plan.model_dump()
    if hasattr(plan, "__dataclass_fields__"):
        return asdict(plan)
    return dict(getattr(plan, "__dict__", {}) or {})
