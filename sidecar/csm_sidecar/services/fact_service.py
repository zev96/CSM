"""事实更新传导（§7）—— vault 型号指纹 vs 基线，检测变更供通知 + 历史标记。

detect_changes 在 lifespan 启动扫完 + POST /api/vault/scan 后调；首建基线不报变更。
_pending 是 session 级变更队列，GET /api/facts/changes 一次性取走并清空。
"""
from __future__ import annotations

import datetime
import logging
import threading

from csm_core.brand_memory.fingerprint import diff_canonical, spec_fingerprint
from csm_core.brand_memory.resolver import resolve_memory
from csm_core.feedback import storage as feedback_storage

from . import config_service

logger = logging.getLogger(__name__)

_pending: list[dict] = []
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _iter_models(registry):
    """(brand, model) for every registry model。

    category 不参与 resolve_memory 的 specs/certs 解析（只透传进 memory.category），
    所以指纹与 category 无关 —— detect 无须枚举 category，传空即可（CP-3）。
    """
    for model in registry.all_models():
        brand = registry.brand_of(model)
        if brand:
            yield brand, model


def detect_changes(index, registry) -> list[dict]:
    """逐型号 resolve_memory → 指纹 vs 基线。首建不报、变更收集并更新基线、入 pending。"""
    cfg = config_service.load()
    own = set(cfg.brand_memory.own_brands)
    baseline = feedback_storage.get_model_fingerprints()  # model -> (fp, specs_json)
    changes: list[dict] = []
    new_rows: list[tuple[str, str, str]] = []
    for brand, model in _iter_models(registry):
        try:
            mem = resolve_memory(brand, model, "", index, own_brands=own)
            fp, canonical = spec_fingerprint(mem)
        except Exception:
            # 单型号 resolve/指纹失败只跳过该型号，不 abort 整轮（其余型号照建基线）。
            logger.debug("resolve/fingerprint failed for %s/%s (skip)", brand, model, exc_info=True)
            continue
        old = baseline.get(model)
        if old is None:
            new_rows.append((model, fp, canonical))  # 首建基线，不报变更
        elif old[0] != fp:
            changes.append({
                "model": model,
                "changed": diff_canonical(old[1], canonical),
                "detected_at": _now_iso(),
            })
            new_rows.append((model, fp, canonical))  # 更新基线
    if new_rows:
        feedback_storage.upsert_model_fingerprints(new_rows, now=_now_iso())
    if changes:
        with _lock:
            _pending.extend(changes)
    return changes


def drain_changes() -> list[dict]:
    """取走并清空 pending 变更队列（GET /api/facts/changes）。"""
    with _lock:
        out = list(_pending)
        _pending.clear()
        return out


def diff_for_model(model: str, index, registry) -> list[dict]:
    """某型号「最近成稿快照 vs 当前 vault」字段 diff（§7.3 hover）。无快照/无型号 → []。"""
    old_specs = feedback_storage.get_latest_snapshot_specs(model)
    if old_specs is None:
        return []
    brand = registry.brand_of(model)
    if not brand:
        return []
    cfg = config_service.load()
    try:
        mem = resolve_memory(brand, model, "", index, own_brands=set(cfg.brand_memory.own_brands))
    except Exception:
        return []
    _, canonical = spec_fingerprint(mem)
    return diff_canonical(old_specs, canonical)


def reset_for_test() -> None:
    with _lock:
        _pending.clear()
