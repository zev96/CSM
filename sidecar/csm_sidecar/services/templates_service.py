"""Template CRUD wrapper.

Templates are stored as ``<id>.json`` files in a directory. We resolve
that directory in this order:

1. The parent directory of ``AppConfig.default_template`` if set.
2. ``<config_dir>/templates`` as a fallback.

The directory is created on first write so the user doesn't need a
manual setup step before saving their first template.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from csm_core.template.loader import list_templates, load_template, save_template
from csm_core.template.schema import Template

from . import config_service


def resolve_dir() -> Path:
    cfg = config_service.load()
    if cfg.default_template:
        return Path(cfg.default_template).parent
    return config_service.get_path().parent / "templates"


def list_all() -> list[dict[str, Any]]:
    """Return [{id, name, path}] for every template in the resolved dir."""
    d = resolve_dir()
    out: list[dict[str, Any]] = []
    for name, path in list_templates(d):
        out.append({
            "id": path.stem,
            "name": name,
            "path": str(path),
        })
    return out


def get_one(template_id: str) -> Template:
    path = resolve_dir() / f"{template_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"template not found: {template_id}")
    return load_template(path)


def create(template: Template) -> dict[str, Any]:
    """Persist *template* under ``<dir>/<template.id>.json``.

    Refuses to overwrite — call :func:`update` to replace an existing one.
    """
    d = resolve_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{template.id}.json"
    if path.exists():
        raise FileExistsError(f"template id already exists: {template.id}")
    save_template(template, path)
    return {"id": template.id, "name": template.name, "path": str(path)}


def update(template: Template) -> dict[str, Any]:
    d = resolve_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{template.id}.json"
    if not path.exists():
        raise FileNotFoundError(f"template not found: {template.id}")
    save_template(template, path)
    return {"id": template.id, "name": template.name, "path": str(path)}


def delete(template_id: str) -> None:
    path = resolve_dir() / f"{template_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"template not found: {template_id}")
    path.unlink()
