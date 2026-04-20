"""Persistent user settings loaded from/saved to settings.json."""
from __future__ import annotations
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

Provider = Literal["mock", "anthropic", "deepseek"]


class AppConfig(BaseModel):
    vault_root: str | None = None
    out_dir: str | None = None
    default_provider: Provider = "mock"
    api_keys: dict[str, str] = Field(default_factory=dict)
    default_template: str | None = None
    skill_dir: str | None = None
    last_seed: int = 0
    default_model: dict[str, str] = Field(default_factory=dict)


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        return AppConfig()
    try:
        return AppConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
