"""Dedup index management.

A single :class:`DedupAnalyzer` instance lives for the sidecar process,
holding the "history" and "vault" indexes in memory. We save them to
disk after each build so an app restart doesn't force a re-scan; on
sidecar startup we lazy-load them on first ``analyze`` rather than
eagerly at import (avoids a slow boot when the user hasn't built yet).
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from csm_core.dedup.analyzer import DedupAnalyzer
from csm_core.dedup.report import DuplicateReport

from ..event_bus import bus
from . import config_service

logger = logging.getLogger(__name__)

DedupKind = Literal["history", "vault"]

_analyzer: DedupAnalyzer | None = None
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dedup")
# Track loaded kinds so analyze() can lazy-load on demand without
# repeatedly hitting disk.
_loaded_kinds: set[str] = set()


def get_analyzer() -> DedupAnalyzer:
    global _analyzer
    if _analyzer is None:
        with _lock:
            if _analyzer is None:
                _analyzer = DedupAnalyzer()
    return _analyzer


def _index_dir() -> Path:
    """Where DedupIndex .pkl files live. Co-located with settings.json so
    a per-installation backup of config + index is one folder."""
    return config_service.get_path().parent / "dedup-indexes"


def _ensure_kind_loaded(kind: DedupKind) -> bool:
    """Try to load ``kind`` from disk if not already in memory.

    Returns True if the index is loaded (either was already, or load
    succeeded), False if no on-disk index exists yet.
    """
    if kind in _loaded_kinds:
        return True
    analyzer = get_analyzer()
    if analyzer.index_doc_count(kind) > 0:
        _loaded_kinds.add(kind)
        return True
    d = _index_dir()
    if not d.exists():
        return False
    try:
        analyzer.load(d, kinds=(kind,))  # type: ignore[arg-type]
        _loaded_kinds.add(kind)
        return analyzer.index_doc_count(kind) > 0
    except Exception:
        # Missing or corrupt index file — caller should treat as "no index yet".
        logger.exception("dedup index load failed for kind=%s", kind)
        return False


def _resolve_root(kind: DedupKind) -> Path:
    cfg = config_service.load()
    if kind == "history":
        if not cfg.dedup_history_dir:
            raise ValueError("AppConfig.dedup_history_dir is unset")
        return Path(cfg.dedup_history_dir)
    if not cfg.vault_root:
        raise ValueError("AppConfig.vault_root is unset")
    return Path(cfg.vault_root)


# ── Public API ──────────────────────────────────────────────────────────────
def submit_build(kind: DedupKind) -> str:
    """Kick off an index build. Returns ``job_id`` for SSE subscription.

    Events emitted on ``/api/events/{job_id}``:
    - ``progress``: ``done``, ``total``, ``percent``
    - ``done``: ``kind``, ``doc_count``
    - ``error``: ``error``
    """
    job_id = bus.create_job()
    _executor.submit(_run_build, job_id, kind)
    return job_id


def _run_build(job_id: str, kind: DedupKind) -> None:
    try:
        root = _resolve_root(kind)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"dedup root not found: {root}")
        analyzer = get_analyzer()

        def _on_progress(done: int, total: int) -> None:
            percent = (done / total) if total else 0.0
            bus.publish(
                job_id, "progress",
                done=done, total=total,
                percent=round(percent * 100, 1),
            )

        analyzer.build_index(root, kind=kind, progress_cb=_on_progress)
        # Persist to disk so analyze() across restart doesn't need a re-scan.
        out_dir = _index_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        analyzer.save(out_dir)
        _loaded_kinds.add(kind)

        bus.finish(
            job_id, kind=kind,
            doc_count=analyzer.index_doc_count(kind),
        )
    except Exception as e:
        logger.exception("dedup build job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")


def analyze(text: str, kind: DedupKind) -> dict[str, Any]:
    """Synchronous analyze. Returns a JSON-friendly dict."""
    analyzer = get_analyzer()
    if not _ensure_kind_loaded(kind):
        # No index yet — return an empty report rather than 404 so UI
        # can render "no comparison available" without special-casing.
        return _report_to_dict(DuplicateReport.empty(kind))
    report = analyzer.analyze(text, kind=kind)
    return _report_to_dict(report)


def index_status() -> dict[str, Any]:
    """Doc count + on-disk presence for both kinds. Powers settings UI."""
    analyzer = get_analyzer()
    out: dict[str, Any] = {}
    for k in ("history", "vault"):
        # Probe load if not in memory yet.
        if k not in _loaded_kinds:
            _ensure_kind_loaded(k)  # type: ignore[arg-type]
        out[k] = {
            "doc_count": analyzer.index_doc_count(k),
            "loaded": k in _loaded_kinds,
        }
    return out


def _report_to_dict(report: DuplicateReport) -> dict[str, Any]:
    """asdict() recursively serializes nested SegmentHit/TopMatch dataclasses,
    then we ISO-format the datetime."""
    d = asdict(report)
    if isinstance(d.get("computed_at"), object):
        ca = report.computed_at
        d["computed_at"] = ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
    return d
