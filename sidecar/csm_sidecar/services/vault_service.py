"""Vault service — 统一索引入口（增量快路径 + 全量兜底）。

get()  —— 常规入口：增量刷新（配置关/异常自动回退全量）。
scan() —— 强制全量重建（「重建索引」按钮 / 写盘后失效重建），直调
scan_vault：回退路径与增量代码完全独立，增量索引出 bug 时兜底不受牵连。
IncrementalIndexer 非线程安全，生成作业跑在线程池里会并发进来 ——
本层用 RLock 串行化（RLock 而非 Lock：get() 的异常回退会重入 scan()）。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from csm_core.vault.index_cache import IncrementalIndexer
from csm_core.vault.note_parser import ParsedNote
from csm_core.vault.scanner import VaultIndex, scan_vault

from . import config_service

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_indexer = IncrementalIndexer()
_index: VaultIndex | None = None


def get(root: Path) -> VaultIndex:
    """统一入口：增量刷新；vault_incremental=False 或异常 → 全量。"""
    global _index
    if not config_service.load().vault_incremental:
        return scan(root)
    with _lock:
        try:
            _index = _indexer.refresh(Path(root))
        except Exception:
            logger.warning("增量索引失败，回退全量扫", exc_info=True)
            return scan(root)
        return _index


def scan(root: Path) -> VaultIndex:
    """强制全量重建。reset 保证下次 get() 全量重建增量缓存。"""
    global _index
    with _lock:
        _indexer.reset()
        _index = scan_vault(Path(root))
        return _index


def cached() -> VaultIndex | None:
    return _index


def invalidate() -> None:
    global _index
    with _lock:
        _index = None
        _indexer.reset()


def note_to_dict(note: ParsedNote) -> dict[str, Any]:
    """Serialize a ParsedNote for HTTP responses.

    The full ``raw_body`` is omitted from list responses (typical note runs
    1–10KB; a vault list of 1k notes would be 1–10MB). Callers needing the
    body fetch a single note via ``GET /api/vault/notes/{id}`` (added later
    if a UI screen needs it).
    """
    return {
        "id": note.id,
        "path": str(note.path),
        "frontmatter": note.frontmatter,
        "variant_count": len(note.variants),
    }


def index_summary(index: VaultIndex) -> dict[str, Any]:
    return {
        "root": str(index.root),
        "note_count": len(index.notes),
        "warnings": index.warnings,
    }
