"""Configuration service — wraps csm_core.config for the sidecar.

Holds a process-global path resolved at startup. Tests inject a tmp path
via :func:`init` to avoid touching the user's real settings.json.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from csm_core import config as core_config
from csm_core.config import AppConfig

_path: Path | None = None


def init(path: Path | None = None) -> Path:
    """Set (or reset) the settings.json path. Returns the resolved path."""
    global _path
    _path = Path(path) if path is not None else core_config.default_config_path()
    return _path


def get_path() -> Path:
    if _path is None:
        return init()
    return _path


def load() -> AppConfig:
    return core_config.load_config(get_path())


def save(cfg: AppConfig) -> None:
    core_config.save_config(cfg, get_path())


def patch(updates: dict[str, Any]) -> AppConfig:
    """Apply a partial update on top of the current config.

    Deep-merge: nested dicts (e.g. ``{"monitor": {"alert_top_n": 7}}``) are
    merged into the existing object rather than replacing it wholesale, so
    callers can flip a single nested knob without re-sending every other
    field. Top-level non-dict values (``vault_root``, ``default_provider``,
    etc.) are replaced as-is. Validation happens via ``AppConfig.model_validate``.
    """
    current = load().model_dump()
    merged = _deep_merge(current, updates)
    new_cfg = AppConfig.model_validate(merged)
    save(new_cfg)
    return new_cfg


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
