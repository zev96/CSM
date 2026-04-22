"""Load and save templates as JSON."""
from __future__ import annotations
import json
from pathlib import Path
from .schema import Template


def load_template(path: Path) -> Template:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
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
