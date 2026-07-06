"""Aggregation views — sidecar-only adapters that turn the contents of
``dedup_history_dir`` into the shapes the prototype's home screen expects.

These don't belong in csm_core because they're UI-shaped (calendar grids,
"this-week" buckets, recent-doc cards) — the underlying data is just the
exported markdown mirrors on disk (see export_service._mirror_to_history).
"""
from __future__ import annotations

import calendar as _calendar
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import frontmatter

from csm_core.export.markdown import extract_title

from . import config_service

logger = logging.getLogger(__name__)


# ── Recent docs (home screen) ──────────────────────────────────────────────
def list_recent(*, limit: int = 5, days: int = 7) -> dict[str, Any]:
    """Return recent .md files under ``dedup_history_dir``, newest first."""
    history_dir = _resolve_history_dir()
    if history_dir is None or not history_dir.exists():
        return {"count": 0, "documents": []}
    cutoff = datetime.now() - timedelta(days=days)
    items: list[dict[str, Any]] = []
    for f in _iter_exported(history_dir):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        items.append({
            "path": str(f),
            "filename": f.name,
            "title": _doc_title(f),
            "template_name": _doc_template_name(f),
            "words": _doc_word_count(f),
            "modified_at": mtime.isoformat(),
            "format": "docx" if f.suffix.lower() == ".docx" else "markdown",
        })
    items.sort(key=lambda d: d["modified_at"], reverse=True)
    top = items[:limit]
    _enrich_stale(top)
    return {"count": len(top), "documents": top}


def _enrich_stale(items: list[dict[str, Any]]) -> None:
    """§7.3：按 path 关联 creation_record → 快照指纹 != 当前基线则标过期。

    追加 facts_stale/stale_models/record 三字段（旧前端不读、形状兼容）。全程
    fail-safe：先给每项设默认，再尝试增强 —— 反馈层任何故障都不影响最近文档列表。
    """
    for it in items:
        it["facts_stale"] = False
        it["stale_models"] = []
        it["record"] = None
    if not items:
        return
    try:
        from csm_core.feedback import storage as feedback_storage
        baseline = feedback_storage.get_model_fingerprints()  # model -> (fp, specs_json)
    except Exception:
        logger.debug("stale enrich: baseline 加载失败（monitor.db 未就绪？）", exc_info=True)
        return
    for it in items:
        try:
            rec = feedback_storage.find_creation_by_document(it["path"])
            if rec is None:
                continue
            stale = [
                snap.model
                for snap in feedback_storage.get_fact_snapshots_for_record(rec.id)
                if (cur := baseline.get(snap.model)) is not None and cur[0] != snap.fingerprint
            ]
            it["facts_stale"] = bool(stale)
            it["stale_models"] = stale
            it["record"] = {
                "keyword": rec.keyword, "template_id": rec.template_id, "title": rec.title,
                "angle_json": rec.angle_json, "skill_chain_json": rec.skill_chain_json,
                "mode": rec.mode, "models_json": rec.models_json,
                "contract_mode": rec.contract_mode,
            }
        except Exception:
            logger.debug("stale enrich 失败：%s", it.get("path"), exc_info=True)


def _doc_title(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    try:
        post = frontmatter.loads(text)
        if post.metadata.get("title"):
            return str(post.metadata["title"])
        return extract_title(post.content) or path.stem
    except Exception:
        return extract_title(text) or path.stem


def _doc_template_name(path: Path) -> str | None:
    if path.suffix.lower() == ".docx":
        return None
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except (OSError, Exception):  # noqa: BLE001 — robustness
        return None
    return post.metadata.get("template") or post.metadata.get("template_name")


def _doc_word_count(path: Path) -> int:
    """Rough character count for the article body (Chinese-friendly)."""
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document  # local import: heavy
            doc = Document(str(path))
            return sum(len(p.text) for p in doc.paragraphs)
        except Exception:
            return 0
    try:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        return _count_chars(post.content)
    except Exception:
        return 0


def _count_chars(text: str) -> int:
    """Char count excluding whitespace and markdown punctuation. Matches
    what the legacy GUI 字数 panel showed."""
    return sum(1 for c in (text or "") if not c.isspace() and c not in "*#`>-_")


# ── Calendar (home screen 本月排期) ────────────────────────────────────────
def calendar_for_month(year: int, month: int) -> dict[str, Any]:
    """Per-day completion count for ``year-month``.

    ``scheduled`` is returned as all-zeros — csm_core has no scheduling
    module yet (A2 alignment table item 1, kept for UI but not yet
    backed). Filled in when the v2 排期 feature lands.
    """
    history_dir = _resolve_history_dir()
    days_in_month = _calendar.monthrange(year, month)[1]
    done_per_day = [0] * days_in_month  # 0-indexed
    if history_dir is not None and history_dir.exists():
        for f in _iter_exported(history_dir):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
            except OSError:
                continue
            if mtime.year == year and mtime.month == month:
                done_per_day[mtime.day - 1] += 1
    return {
        "year": year,
        "month": month,
        "days": days_in_month,
        "done": done_per_day,
        "scheduled": [0] * days_in_month,  # placeholder
    }


# ── Words stats (home 问候条 + activity bars) ──────────────────────────────
def words_for_range(range_: str) -> dict[str, Any]:
    if range_ not in ("yesterday", "this-week"):
        raise ValueError(f"unsupported range: {range_!r}")
    today = date.today()
    if range_ == "yesterday":
        start = today - timedelta(days=1)
        end_exclusive = today
    else:  # this-week — Monday-anchored
        start = today - timedelta(days=today.weekday())
        end_exclusive = today + timedelta(days=1)

    history_dir = _resolve_history_dir()
    by_day: dict[date, int] = {}
    total = 0
    if history_dir is not None and history_dir.exists():
        for f in _iter_exported(history_dir):
            try:
                fdate = datetime.fromtimestamp(f.stat().st_mtime).date()
            except OSError:
                continue
            if not (start <= fdate < end_exclusive):
                continue
            words = _doc_word_count(f)
            total += words
            by_day[fdate] = by_day.get(fdate, 0) + words

    bars = []
    cur = start
    while cur < end_exclusive:
        bars.append({
            "date": cur.isoformat(),
            "weekday": cur.strftime("%a"),
            "words": by_day.get(cur, 0),
            "polished": 0,  # csm_core doesn't track polish provenance — A2: returned as 0
        })
        cur += timedelta(days=1)
    return {
        "range": range_,
        "start": start.isoformat(),
        "end": end_exclusive.isoformat(),
        "total_words": total,
        "by_day": bars,
    }


# ── Helpers ────────────────────────────────────────────────────────────────
def _resolve_history_dir() -> Path | None:
    """Source-of-truth folder for 'recent docs' / calendar / words stats.

    Switched from ``out_dir`` to ``dedup_history_dir`` in 0.5.0 — the
    history dir holds .md mirrors of every export and is the only place
    the home screen needs to scan. See:
    docs/superpowers/specs/2026-05-12-recent-history-and-vault-attrs-design.md
    """
    cfg = config_service.load()
    return Path(cfg.dedup_history_dir) if cfg.dedup_history_dir else None


def _iter_exported(history_dir: Path):
    """Yield every .md under ``history_dir`` (recursive). Skips hidden files.

    History dir mirrors are .md only; we deliberately ignore .docx so a
    stray docx the user dropped in there doesn't pollute aggregations.
    """
    for p in history_dir.rglob("*.md"):
        if p.name.startswith("."):
            continue
        yield p
