"""Template CRUD wrapper.

Templates are stored as ``<id>.json`` files in a directory. We resolve
that directory from ``AppConfig.default_template`` (falling back to
``<config_dir>/templates``).

``default_template`` carries one of two shapes depending on how it was
set, and both must work:

* A **folder** path — what Settings → 存储路径 → 默认模板目录 writes today
  (its picker is ``directory: true``). The folder itself is the library.
* A **.json file** path — the legacy/hand-typed shape, where the file's
  *parent* directory is the library.

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
        p = Path(cfg.default_template)
        # 之前这里无条件 ``.parent``，把用户用文件夹选择器选的目录截成了它
        # 的上级目录 —— 选了 ``D:\Templates`` 实际扫的是 ``D:\``，里面的模板
        # 一个都识别不到。现在区分两种形态：指向 .json 文件 → 用父目录；
        # 否则（目录，含尚未创建的目录路径）→ 目录本身就是模板库。
        if p.is_dir():
            return p
        if p.suffix.lower() == ".json":
            return p.parent
        return p
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
