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


class MonitorConfig(BaseModel):
    """Settings for the monitor module (Zhihu question / multi-platform comments).

    Lives as a sub-model on AppConfig so it round-trips through the same
    JSON file as the rest of the user's settings. The actual monitor data
    (tasks, results, credentials) goes into a separate sqlite db under
    ``<config_dir>/monitor.db`` — this model only carries small,
    user-facing knobs.
    """

    enabled: bool = False
    # Top-N threshold for the rank-fell-out alert. When a Zhihu task's
    # target keyword leaves Top N (or a comment leaves Top N hot list),
    # MonitorScheduler emits ``alert_triggered``. Default 5 matches the
    # "first page of answers" intuition.
    alert_top_n: int = 5
    # Per-platform max concurrent in-flight tasks. Higher numbers blow
    # past anti-bot rate limits — keep conservative.
    concurrency_per_platform: int = 2
    # Random delay window (seconds) inserted between requests to the same
    # platform. Spread mimics a human's browsing tempo and is the single
    # biggest knob for staying under risk-control radar.
    request_delay_min: float = 5.0
    request_delay_max: float = 15.0
    # Cooldown window (hours) before the same task can fire another
    # rank-fell-out alert. Without this every scheduled tick would re-fire
    # the alert until the rank recovers.
    alert_cooldown_hours: int = 24
    # Path to the user's local Chrome executable. Empty = let DrissionPage
    # auto-detect. Only consulted when the curl_cffi fast path fails over
    # to the browser fallback.
    chrome_path: str = ""
    # Whether to auto-trigger the AI summarizer (Top-answers → Vault note)
    # when a Zhihu task completes. Off by default to avoid burning LLM
    # tokens on every poll.
    ai_summarize_zhihu: bool = False
    # Whether to auto-classify comment sentiment with the LLM after each
    # comment-monitoring run.
    ai_classify_comments: bool = False


class AppConfig(BaseModel):
    user_name: str | None = None
    user_product: str | None = None
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
    # Per-provider "this (key, model, base_url) tested OK" markers. Set
    # when the user clicks 测试连接 and the ping returns; restored on next
    # launch so the green 已连接 badge survives restarts. Stored as a
    # truncated SHA-256 of ``key|model|base_url`` rather than the raw
    # values — the api_key is already in this same file, but the hash
    # keeps a careless settings.json paste from leaking working triplets
    # in a second, redundant place.
    provider_test_signatures: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 180
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

    # ── Monitor (Zhihu / comment-platforms) ────────────────────────────
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)


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
