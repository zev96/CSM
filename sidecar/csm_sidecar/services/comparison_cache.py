"""job_id → 横评元数据 LRU 缓存（镜像 assembler_service 的 plan 缓存）。

_finalize_job 命中此缓存 → 由 models 重解析 scopes、跳过 plan 路径。"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class ComparisonMeta:
    models: list[str]
    category: str
    keyword: str
    title: str | None
    tone: str | None
    skill_chain: list[str] | None
    contract_mode: str | None


_cache: "OrderedDict[str, ComparisonMeta]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def cache_comparison(
    job_id: str, *, models: list[str], category: str, keyword: str,
    title: str | None, tone: str | None, skill_chain: list[str] | None,
    contract_mode: str | None,
) -> None:
    with _lock:
        _cache[job_id] = ComparisonMeta(
            models=models, category=category, keyword=keyword, title=title,
            tone=tone, skill_chain=skill_chain, contract_mode=contract_mode)
        _cache.move_to_end(job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def get_comparison(job_id: str) -> ComparisonMeta | None:
    with _lock:
        e = _cache.get(job_id)
        if e is not None:
            _cache.move_to_end(job_id)
        return e


def reset_for_test() -> None:
    with _lock:
        _cache.clear()
