"""Pending-export cache for the fact-check gate + the resume/export step.

事实核对命中越界时，generate_service 把导出所需的一切（plan/out_dir/
keyword/fmt + 白名单两集合）按 job_id 缓存到这里，并以 done(blocked) 收尾
而不导出。前端审查面板（Plan 5）让用户改文案 / 标通用 / 放行后 POST
/api/generate/{job_id}/export → resolve_and_export 用放行项补进白名单重核
（成稿可能已被用户编辑），干净则落盘。

缓存 LRU 有界（仿 assembler_service）—— 条目小（plan 树 + 两个集合）。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csm_core.assembler.plan import AssemblyPlan
from csm_core.export.markdown import ExportFormat, export_article
from csm_core.factcheck import check_facts


@dataclass
class _Pending:
    plan: AssemblyPlan
    out_dir: Path
    keyword: str
    fmt: ExportFormat
    allowed_numbers: set[float]
    allowed_certs: set[str]


_cache: "OrderedDict[str, _Pending]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def cache_pending(
    job_id: str, *, plan: AssemblyPlan, out_dir: Path, keyword: str,
    fmt: ExportFormat, allowed_numbers: set[float], allowed_certs: set[str],
) -> None:
    with _lock:
        _cache[job_id] = _Pending(
            plan=plan, out_dir=Path(out_dir), keyword=keyword, fmt=fmt,
            allowed_numbers=set(allowed_numbers), allowed_certs=set(allowed_certs),
        )
        _cache.move_to_end(job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def get_pending(job_id: str) -> _Pending | None:
    with _lock:
        e = _cache.get(job_id)
        if e is not None:
            _cache.move_to_end(job_id)
        return e


def resolve_and_export(
    job_id: str, *, final_text: str,
    released_numbers: list[float], released_certs: list[str],
) -> dict[str, Any]:
    """带放行项重核（成稿可能已被编辑）；干净则导出。

    返回 {"ok": True, "document", "format", "title"} 或
    {"ok": False, "violations": [...]}。未知 job_id（过期 / 从未被拦）→ KeyError。
    """
    e = get_pending(job_id)
    if e is None:
        raise KeyError(job_id)
    allowed_numbers = e.allowed_numbers | {float(n) for n in released_numbers}
    allowed_certs = e.allowed_certs | set(released_certs)
    report = check_facts(
        final_text, allowed_numbers=allowed_numbers, allowed_certs=allowed_certs,
    )
    if not report.ok:
        return {"ok": False,
                "violations": [v.model_dump() for v in report.violations]}
    e.out_dir.mkdir(parents=True, exist_ok=True)
    paths = export_article(
        out_dir=e.out_dir, keyword=e.keyword, final_text=final_text,
        plan=e.plan, fmt=e.fmt,
    )
    with _lock:
        _cache.pop(job_id, None)
    return {"ok": True, **paths}


def reset_for_test() -> None:
    with _lock:
        _cache.clear()
