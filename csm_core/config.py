"""Persistent user settings — single source of truth for both PyQt GUI (legacy)
and the upcoming Tauri+sidecar architecture.

Migration note: this module was moved here from ``csm_gui.config`` so the
sidecar can own configuration without depending on PyQt. ``csm_gui.config``
remains as a thin re-export shim during the transition window — see
docs/migration/feature-ui-mapping.md and the migration plan.
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

Provider = Literal["mock", "anthropic", "deepseek", "openai", "gemini", "qwen"]
CloseAction = Literal["minimize_to_tray", "quit"]


class BaiduKeywordConfig(BaseModel):
    """settings.monitor.baidu_keyword.*"""

    headless_default: bool = True
    captcha_visible_timeout_s: int = 90
    captcha_max_promotions: int = 1
    serp_pacing_seconds: int = 5
    breaker_failures: int = 3
    breaker_cooldown_seconds: int = 600

    # ── Result filtering: 默认排除的"非软文"域名 ──────────────────
    # 用户跑百度排名的目的是追"自家软文"的卡位，但 SERP 经常混进
    # B2B 采购站（jd, 1688）、电商列表（taobao, tmall）—— 即便品牌
    # 词命中，那也不是软文。下面这份默认黑名单会从 SERP 结果里
    # 整条剔除，剔除后再重新编号 #1 #2 #3。
    #
    # 单独门户网站（如自家品牌官网）属于每个任务自己的语义，
    # 写在 task.config.exclude_domains 里（per-task list），跟这里
    # 的全局默认合并使用。
    #
    # 匹配规则：host == pattern  OR  host endswith ('.' + pattern)
    # 所以 "jd.com" 同时命中 "jd.com" / "www.jd.com" / "mall.jd.com"。
    default_excluded_domains: list[str] = Field(default_factory=lambda: [
        # B2B / 采购站
        "1688.com",
        "alibaba.com",
        "yiwugo.com",
        # 综合电商
        "jd.com",
        "taobao.com",
        "tmall.com",
        "tmall.hk",
        "tb.cn",
        "suning.com",
        "yhd.com",
        "vip.com",
        "vipshop.com",
        "pinduoduo.com",
        "pdd.com",
        "gome.com.cn",
        "kaola.com",
        # 海淘 / 跨境
        "amazon.cn",
        "ymatou.com",
        # 微商 / 小程序商城
        "youzan.com",
        "mogu.com",
    ])


class MonitorConfig(BaseModel):
    """Settings for the monitor module (Zhihu question / multi-platform comments).

    Lives as a sub-model on AppConfig so it round-trips through the same
    JSON file as the rest of the user's settings. The actual monitor data
    (tasks, results, credentials) goes into a separate sqlite db under
    ``<config_dir>/monitor.db`` — this model only carries small,
    user-facing knobs.
    """

    enabled: bool = False
    alert_top_n: int = 5
    concurrency_per_platform: int = 2
    request_delay_min: float = 5.0
    request_delay_max: float = 15.0
    alert_cooldown_hours: int = 24
    chrome_path: str = ""
    ai_summarize_zhihu: bool = False
    ai_classify_comments: bool = False

    # ── 浏览器引擎选择 ───────────────────────────────────────────
    # patchright = Playwright + stealth patches，开箱反爬通过率高（推荐）
    # drission = 老路径，留作兜底；patchright 装不上或者本机 Chrome 已经
    #            被绑定到调试端口跑不起来时切到这条
    browser_engine: Literal["patchright", "drission"] = "patchright"

    # ── 多账号轮换 ───────────────────────────────────────────────
    # 用户在 Cookie 池里有 2+ 条同平台 cookie 时才有意义。关闭时
    # 永远用 pick() 返回的第一条（最久没用 + fail_count 最低）。
    multi_account_rotation: bool = False
    # 每个 cookie 连续承担 N 个任务后强制切下一条。1 = 每个任务都换。
    # 2-3 是经验上的安全档：太小流量太碎 cookie 看起来不像真人，太大
    # 又起不到分摊作用。
    tasks_per_account: int = 2
    # 命中 unhuman / 403 / signin 时给当前 cookie 加多久冷却（分钟）。
    # 30 分钟够 zhihu 反爬 token 自动 refresh 一轮；用户也能在 UI
    # 看到这条 cookie 暂时不可用，去 Cookie 池手动重抓。
    cookie_cooldown_minutes: int = 30

    # ── 百度关键词监控 ──────────────────────────────────────────────
    baidu_keyword: BaiduKeywordConfig = Field(default_factory=BaiduKeywordConfig)


class AppConfig(BaseModel):
    user_name: str | None = None
    user_product: str | None = None
    vault_root: str | None = None
    out_dir: str | None = None
    # None = 用户尚未选择默认 provider — sidecar 在收到生成请求时会拒绝并要求
    # 用户先去设置页选一个。这避免了 "mock" 作为兜底导致用户拿到 "mock response"
    # 占位结果还以为是真生成。
    default_provider: Provider | None = None
    # TODO(task-2): move api_keys to OS keyring (keyring package) — plaintext on disk is below user expectations.
    # Tracked for sidecar migration: see csm_core.config.keyring_store below for the new code path.
    api_keys: dict[str, str] = Field(default_factory=dict)
    default_template: str | None = None
    skill_dir: str | None = None
    last_seed: int = 0
    default_model: dict[str, str] = Field(default_factory=dict)
    base_urls: dict[str, str] = Field(default_factory=dict)
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

    # ── Outreach AI prompts (Phase 3) ──────────────────────────────────
    # 空字符串 = 用 mining_ai_service 里的内置默认 prompt。用户在设置页
    # 改了之后，下次调用 AI 速览 / AI 建议时优先用这里的值。
    # 自定义格式：单一字符串 = system；含 "---user---" 分隔符 = (system, user) 两段。
    mining_summary_prompt: str = ""
    mining_suggest_prompt: str = ""

    # ── Proxy pool ──────────────────────────────────────────────────────────
    # 用户自备 HTTP/SOCKS5 代理列表的配置文件路径（proxies.json 完整路径）。
    # None 或空字符串 = 不启用代理池，所有爬取直连。
    # 格式见 csm_core/browser_infra/proxy_pool.py。
    proxies_path: str | None = Field(default=None, description="Path to proxies.json; None disables proxy pool")


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        logger.debug("settings file not found at %s — using defaults", path)
        return AppConfig()
    try:
        return AppConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, ValidationError, UnicodeDecodeError, OSError) as e:
        logger.warning("Failed to load settings from %s (%s) — using defaults", path, e)
        return AppConfig()


def save_config(cfg: AppConfig, path: Path) -> None:
    """Atomic write: tmp file + os.replace prevents truncation on crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def default_config_dir() -> Path:
    """Resolve the per-user config directory without depending on Qt.

    Replaces the QStandardPaths-based path used by the legacy GUI shell.
    Picks the first matching strategy:

    * Windows: ``%LOCALAPPDATA%/CSM-Data``  (was ``CSM/CSM`` pre-v0.4.5)
    * macOS:   ``~/Library/Application Support/CSM/CSM``
    * Linux:   ``$XDG_CONFIG_HOME/CSM`` (fallback ``~/.config/CSM``)

    Windows path note: pre-v0.4.5 we used ``%LOCALAPPDATA%/CSM/CSM`` which
    sat **inside** the NSIS install dir (``%LOCALAPPDATA%/CSM``). The hot-
    update flow renames the install dir wholesale, which would have wiped
    user data along with the old binaries. Moving to ``CSM-Data`` puts the
    data out of the install path entirely. See ``legacy_config_dir_win``
    for the old path that migrate_legacy_config_dir() copies from.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "CSM-Data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CSM" / "CSM"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "CSM"


def legacy_config_dir_win() -> Path:
    """Pre-v0.4.5 Windows data dir. Only meaningful for one-shot migration."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "CSM" / "CSM"


def migrate_legacy_config_dir() -> bool:
    """Copy pre-v0.4.5 Windows data into the new dir if applicable.

    Conditions to trigger (Windows only):
      - Old dir ``%LOCALAPPDATA%/CSM/CSM`` exists with at least one file
      - New dir ``%LOCALAPPDATA%/CSM-Data`` does NOT exist (or is empty)

    Strategy: shutil.copytree (don't delete old) — leaves the old dir as
    a safety net for the user to manually recover from if anything looks
    off in the new dir. A future release can decide to clean it up.

    Returns True if a copy was performed, False if skipped (no old data,
    or new already populated).
    """
    if sys.platform != "win32":
        return False
    old = legacy_config_dir_win()
    new = default_config_dir()
    if not old.is_dir():
        return False
    # Consider new as "already populated" if settings.json is present —
    # cheaper than os.scandir + safer (don't treat an accidental mkdir
    # without files as "already migrated").
    if (new / "settings.json").exists():
        return False
    try:
        import shutil
        if new.exists():
            # New dir exists but has no settings.json. Maybe partial
            # migration from a previous run — merge instead of nuking.
            # shutil.copytree with dirs_exist_ok=True (Py 3.8+) handles
            # this without raising.
            shutil.copytree(str(old), str(new), dirs_exist_ok=True)
        else:
            shutil.copytree(str(old), str(new))
        logger.info("migrated legacy config dir %s -> %s (old retained as backup)", old, new)
        return True
    except OSError as e:
        # Don't propagate — sidecar can still start with an empty new dir.
        # The user just won't see their old data; they can manually copy.
        logger.exception("legacy config dir migration failed: %s", e)
        return False


def default_config_path() -> Path:
    return default_config_dir() / "settings.json"


def default_templates_dir() -> Path:
    """Per-user templates folder. Created on first sidecar startup if missing.

    Lives alongside settings.json so it survives app reinstall and stays
    writable even when the app is installed to Program Files.
    """
    return default_config_dir() / "Templates"


def default_skills_dir() -> Path:
    """Per-user Skills folder. Same rationale as default_templates_dir."""
    return default_config_dir() / "Skills"


def default_history_dir() -> Path:
    """Per-user history index folder — exports auto-mirror a .md copy here,
    and the home-screen 最近文档 list reads from this dir."""
    return default_config_dir() / "History"


# ── Keyring migration scaffold ──────────────────────────────────────────────
# Filled in during sidecar phase A3 — see migration plan. Kept as a stub so
# both GUI and sidecar already import the same symbol; switching the storage
# backend later won't ripple through callers.

_KEYRING_SERVICE = "CSM"


def get_secret(provider: str) -> str | None:
    """Read an API key for *provider* from the OS credential store.

    During the transition window callers should fall back to ``AppConfig.api_keys``
    if this returns ``None``. Once all writes go through ``set_secret``, the
    plaintext field can be deleted.
    """
    try:
        import keyring  # type: ignore
    except ImportError:
        return None
    try:
        return keyring.get_password(_KEYRING_SERVICE, provider)
    except Exception as e:  # pragma: no cover — keyring backend errors vary by OS
        logger.warning("keyring read failed for %s: %s", provider, e)
        return None


def set_secret(provider: str, value: str) -> bool:
    """Persist an API key for *provider* in the OS credential store.

    Returns True on success, False if the keyring backend is unavailable.
    """
    try:
        import keyring  # type: ignore
    except ImportError:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, provider, value)
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("keyring write failed for %s: %s", provider, e)
        return False


def delete_secret(provider: str) -> bool:
    try:
        import keyring  # type: ignore
        from keyring.errors import PasswordDeleteError  # type: ignore
    except ImportError:
        return False
    try:
        keyring.delete_password(_KEYRING_SERVICE, provider)
        return True
    except PasswordDeleteError:
        return False
    except Exception as e:  # pragma: no cover
        logger.warning("keyring delete failed for %s: %s", provider, e)
        return False
