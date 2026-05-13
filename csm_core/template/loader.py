"""Load and save templates as JSON."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any
from .schema import Template


logger = logging.getLogger(__name__)


def _migrate_competitor_pool_sources(data: dict[str, Any]) -> bool:
    """Auto-migrate competitor_pool blocks with non-notes_query source.

    Older versions of TemplateBuilder defaulted competitor_pool to
    ``brand_pool`` source, but ``csm_core.assembler.sampler.sample_block``
    asserts the source is ``notes_query``. Loading those templates would
    blow up at generate time with ``AssertionError: competitor_pool block
    'xxx' only supports notes_query source``.

    Rewriting the source on load (rather than failing) means old saved
    templates keep opening; user can then fill in the empty module/filter
    via the UI. Returns True if any block was migrated, so caller can
    decide to re-save and stop logging on subsequent loads.
    """
    changed = False
    for block in data.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("kind") != "competitor_pool":
            continue
        src = block.get("source") or {}
        if not isinstance(src, dict):
            continue
        if src.get("type") == "notes_query":
            continue
        logger.warning(
            "template loader: migrating competitor_pool block '%s' from "
            "source.type=%r to notes_query (empty module/filter — fill in via UI)",
            block.get("id"),
            src.get("type"),
        )
        block["source"] = {"type": "notes_query", "module": "", "filter": {}}
        changed = True
    return changed


def load_template(path: Path) -> Template:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    _migrate_competitor_pool_sources(data)
    return Template.model_validate(data)


def save_template(template: Template, path: Path) -> None:
    Path(path).write_text(
        json.dumps(template.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_templates(directory: Path) -> list[tuple[str, Path]]:
    """Scan *directory* for *.json templates, return [(display_name, path), ...].

    Display name falls back to filename stem when the file cannot be parsed.
    Hidden files and anything under `.trash/` are skipped. Results are sorted
    by display name for stable UI rendering.
    """
    d = Path(directory)
    if not d.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for p in d.glob("*.json"):
        if p.name.startswith(".") or ".trash" in p.parts:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            name = str(data.get("name") or p.stem)
        except Exception:
            name = p.stem
        out.append((name, p))
    out.sort(key=lambda t: t[0])
    return out
