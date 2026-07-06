"""反馈学习闭环服务层（§6）—— 采集 fail-open、绝不影响导出。

两个 job_id LRU（镜像 comparison_cache/plan cache 的 50 上限）：
- ``_request_cache``：submit/submit_comparison 时 stash 的请求快照（导出时回填 record 字段）；
- ``_scopes_cache``：finalize 时 stash 的型号事实指纹（导出时落 fact_snapshots）。

``record_export`` 全程吞异常 —— 反馈是副作用，任何失败都不得回传给导出主流程。
"""
from __future__ import annotations

import datetime
import difflib
import json
import logging
import threading
from collections import OrderedDict

from csm_core.feedback import storage as feedback_storage
from csm_core.feedback.model import CreationRecord, FactSnapshot, NoteUsage

from . import assembler_service, chain_service, config_service

logger = logging.getLogger(__name__)

MAX = 50
_request_cache: "OrderedDict[str, dict]" = OrderedDict()
_scopes_cache: "OrderedDict[str, list[FactSnapshot]]" = OrderedDict()
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _lru_put(cache: OrderedDict, key: str, value) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > MAX:
            cache.popitem(last=False)


# ── stash（submit / finalize 时写）────────────────────────────────────────────
def stash_request(job_id: str, snapshot: dict) -> None:
    """submit/submit_comparison 时存请求快照（归一化字段，normal 与 comparison 共形）。"""
    _lru_put(_request_cache, job_id, snapshot)


def stash_scopes(job_id: str, snaps: list[FactSnapshot]) -> None:
    """finalize 时存型号事实指纹（不重解析、无漂移；导出时落 fact_snapshots）。"""
    _lru_put(_scopes_cache, job_id, list(snaps))


def reset_for_test() -> None:
    with _lock:
        _request_cache.clear()
        _scopes_cache.clear()


# ── record_export（导出成功后调；fail-open）──────────────────────────────────
def record_export(
    job_id: str | None, *,
    document_path: str, fmt: str, final_text: str,
    score: float | None = None, score_json: str | None = None,
    lint_unresolved: int = 0, factcheck_blocked: int = 0,
) -> None:
    """导出成功后采集一条 creation_record。**全程 try/except 吞 —— 绝不影响导出。**"""
    try:
        cfg = config_service.load()
        if not cfg.feedback.record:
            return
        if not job_id:
            return  # 纯前端 clientDownload / 无 job → 不采集（v1 边界）
        with _lock:
            snap = _request_cache.get(job_id)
        if snap is None:
            return  # 请求快照丢了（LRU 淘汰/重启）→ 放弃这条（宁缺毋滥）
        note_usage = _extract_note_usage(job_id)
        edit_ratio = _compute_edit_ratio(job_id, final_text)
        with _lock:
            fact_snaps = list(_scopes_cache.get(job_id, []))
        now = _now_iso()
        rec = CreationRecord(
            job_id=job_id, mode=snap.get("mode", "normal"),
            keyword=snap.get("keyword"), template_id=snap.get("template_id"),
            title=snap.get("title"), angle_json=snap.get("angle_json"),
            skill_chain_json=snap.get("skill_chain_json"), models_json=snap.get("models_json"),
            contract_mode=snap.get("contract_mode"),
            document_path=document_path, format=fmt, edit_ratio=edit_ratio,
            lint_unresolved=lint_unresolved, factcheck_blocked=factcheck_blocked,
            score=score, score_json=score_json, created_at=now, exported_at=now,
        )
        feedback_storage.record_creation(rec, note_usage, fact_snaps)
    except Exception:
        logger.exception("record_export failed for job %s (swallowed)", job_id)


def _extract_note_usage(job_id: str) -> list[NoteUsage]:
    """从缓存 plan 递归提取 note 用量。横评（plan=None）/缓存 miss → []。"""
    entry = assembler_service.get_plan(job_id)
    if entry is None:
        return []
    out: list[NoteUsage] = []

    def _walk(results) -> None:
        for br in results:
            for p in getattr(br, "picks", None) or []:
                out.append(NoteUsage(
                    note_id=p.note_id, variant_index=p.variant_index, block_id=br.block_id))
            children = getattr(br, "children", None)
            if children:
                _walk(children)

    _walk(getattr(entry.plan, "results", None) or [])
    return out


def _compute_edit_ratio(job_id: str, export_final: str) -> float | None:
    """链成稿 vs 导出稿的编辑比 = 1 - SequenceMatcher.ratio()。链缓存 miss → None。"""
    state = chain_service.get_state(job_id)
    chain_final = getattr(state, "final_text", None) if state is not None else None
    if not chain_final:
        return None
    return 1.0 - difflib.SequenceMatcher(None, chain_final, export_final).ratio()


# ── rank / 呈现（读）─────────────────────────────────────────────────────────
def get_note_weights() -> dict[str, float]:
    """rank 关 → {}（调用方视作 None，零回归）；开 → storage 聚合权重。

    **fail-open**：这运行在生成热路径（_run_job 的 assemble_plan 参数里），任何失败
    （DB 锁/损坏/config）都退回 {} = 均匀采样 = 零回归，绝不让反馈层拖垮用户的文章
    生成。与 record_export 同哲学（对抗审查发现 rank=ON 时的拖垮缺口）。
    """
    try:
        cfg = config_service.load()
        if not cfg.feedback.rank:
            return {}
        return feedback_storage.get_note_weights(cfg.feedback.min_samples, cfg.feedback.alpha)
    except Exception:
        logger.exception("get_note_weights failed — 退回均匀采样（零回归）")
        return {}


def get_feedback_stats() -> dict:
    return feedback_storage.get_feedback_stats()
