"""Export final article as .md plus .assembly.json snapshot."""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from ..assembler.plan import AssemblyPlan

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("-", name).strip()


def export_article(
    *,
    out_dir: Path,
    keyword: str,
    final_text: str,
    plan: AssemblyPlan,
    prompt_snapshot: dict[str, Any],
) -> dict[str, str]:
    out_dir = Path(out_dir)
    if not out_dir.exists():
        raise FileNotFoundError(f"output directory does not exist: {out_dir}")

    stem = _sanitize_filename(keyword)
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.assembly.json"

    md_path.write_text(final_text, encoding="utf-8")

    snapshot = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "keyword": keyword,
        "plan": plan.model_dump(),
        "prompt_snapshot": prompt_snapshot,
    }
    json_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"markdown": str(md_path), "assembly_json": str(json_path)}
