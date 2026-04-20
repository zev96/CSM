"""Batch execution report — dataclass + atomic I/O."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BatchItem:
    index: int
    keyword: str
    status: Literal["success", "failed"]
    markdown_path: str | None = None
    assembly_json_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    duration_seconds: float = 0.0


@dataclass
class BatchReport:
    batch_id: str
    batch_dir: str
    started_at: str
    finished_at: str | None
    template_path: str
    vault_root: str
    seed: int
    total: int
    items: list[BatchItem] = field(default_factory=list)


def write_report(report: BatchReport, path: Path) -> None:
    """Atomic write: serialize to temp file, then os.replace."""
    path = Path(path)
    data = asdict(report)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def read_report(path: Path) -> BatchReport:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_items = data.pop("items", [])
    report = BatchReport(**data)
    report.items = [BatchItem(**i) for i in raw_items]
    return report
