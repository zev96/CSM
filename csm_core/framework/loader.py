"""Load / save / discover framework JSON files."""
from __future__ import annotations
import json
from pathlib import Path
from .schema import Framework


def load_framework(path: Path) -> Framework:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Framework.model_validate(data)


def save_framework(framework: Framework, path: Path) -> None:
    Path(path).write_text(
        json.dumps(framework.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_frameworks(directory: Path) -> list[tuple[str, Path]]:
    """Scan *directory* for *.json frameworks, return [(display_name, path), ...].

    Display name falls back to filename stem when the file cannot be parsed.
    Hidden files (names starting with '.') are skipped. Results are sorted
    by display name for stable UI rendering.
    """
    d = Path(directory)
    if not d.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for p in d.glob("*.json"):
        if p.name.startswith("."):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            name = str(data.get("name") or p.stem)
        except Exception:
            name = p.stem
        out.append((name, p))
    out.sort(key=lambda t: t[0])
    return out
