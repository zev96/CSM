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
