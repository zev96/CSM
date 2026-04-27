"""Persisted history of exported articles.

Each successful export appends one entry to ``<config_dir>/recent_docs.json``.
Entries carry the data the home recents row needs to render (title, format
chip, mtime, status) plus the absolute path so a future click-through can
open the file.

Cap the stored history at ``MAX_ENTRIES`` to keep the file small — older
records fall off when the cap is reached.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

MAX_ENTRIES = 50
_FILENAME = "recent_docs.json"


@dataclass
class RecentDoc:
    title: str          # display title — usually the keyword / stem
    path: str           # absolute path to the exported file
    fmt: str            # "markdown" | "docx"
    exported_at: str    # ISO timestamp
    status: str = "草稿"  # 草稿 / 已发布 / 归档 — currently always 草稿

    @property
    def exported_dt(self) -> datetime:
        try:
            return datetime.fromisoformat(self.exported_at)
        except ValueError:
            return datetime.fromtimestamp(0)


def _store_path(config_dir: Path) -> Path:
    return Path(config_dir) / _FILENAME


def load_recent(config_dir: Path) -> list[RecentDoc]:
    p = _store_path(config_dir)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[RecentDoc] = []
    for item in raw:
        try:
            out.append(RecentDoc(**item))
        except TypeError:
            continue
    return out


def _save(config_dir: Path, items: Iterable[RecentDoc]) -> None:
    p = _store_path(config_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(it) for it in items]
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


def append_export(config_dir: Path, *, title: str, path: str,
                  fmt: str, status: str = "草稿") -> RecentDoc:
    """Record a new export. Newest entry sits at index 0; duplicates
    pointing at the same path are deduped (newest wins) so re-exporting
    the same article doesn't pollute the history.
    """
    entry = RecentDoc(
        title=title, path=path, fmt=fmt, status=status,
        exported_at=datetime.now().isoformat(timespec="seconds"),
    )
    items = [it for it in load_recent(config_dir) if it.path != path]
    items.insert(0, entry)
    if len(items) > MAX_ENTRIES:
        items = items[:MAX_ENTRIES]
    _save(config_dir, items)
    return entry


def clear_all(config_dir: Path) -> None:
    """Wipe the recent-exports history. The on-disk files are untouched."""
    p = _store_path(config_dir)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            # Fall back to truncation if delete is denied (e.g. file locked).
            _save(config_dir, [])


def relative_when(dt: datetime) -> str:
    """Render a timestamp as a friendly relative string."""
    now = datetime.now()
    delta = now - dt
    if delta.total_seconds() < 60:
        return "刚刚"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)} 分钟前"
    if now.date() == dt.date():
        return f"今天 {dt.strftime('%H:%M')}"
    if (now.date() - dt.date()).days == 1:
        return f"昨天 {dt.strftime('%H:%M')}"
    if delta.days < 30:
        return f"{delta.days} 天前"
    return dt.strftime("%Y-%m-%d")
