"""Persistent user settings loaded from/saved to settings.json."""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

Provider = Literal["mock", "anthropic", "deepseek", "openai", "gemini", "qwen"]
CloseAction = Literal["minimize_to_tray", "quit"]


class AppConfig(BaseModel):
    vault_root: str | None = None
    out_dir: str | None = None
    default_provider: Provider = "mock"
    # TODO(task-2): move api_keys to OS keyring (keyring package) — plaintext on disk is below user expectations.
    api_keys: dict[str, str] = Field(default_factory=dict)
    default_template: str | None = None
    skill_dir: str | None = None
    last_seed: int = 0
    default_model: dict[str, str] = Field(default_factory=dict)
    base_urls: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 60
    concurrency: int = 3
    upload_training_hints: bool = False
    export_format: Literal["markdown", "docx"] = "markdown"
    close_action: CloseAction = "minimize_to_tray"
    tray_first_minimize_shown: bool = False

    # ── Dedup detection ────────────────────────────────────────────────
    dedup_enabled: bool = False
    dedup_history_dir: str = ""
    dedup_threshold_green: int = 15           # %
    dedup_threshold_yellow: int = 30          # %
    dedup_history_last_built: str = ""        # ISO timestamp
    dedup_vault_last_built: str = ""

    # ── Update / hot-upgrade ───────────────────────────────────────────
    update_repo: str = ""    # GitHub "owner/name", 留空 = 不检查更新


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        logger.debug("settings file not found at %s — using defaults", path)
        return AppConfig()
    try:
        return AppConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, ValidationError, UnicodeDecodeError, OSError) as e:
        # ValueError covers json.JSONDecodeError (subclass). Broad enough to catch
        # real corruption without swallowing programming errors.
        logger.warning("Failed to load settings from %s (%s) — using defaults", path, e)
        return AppConfig()


def save_config(cfg: AppConfig, path: Path) -> None:
    """Atomic write: tmp file + os.replace prevents truncation on crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
