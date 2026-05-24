"""探测用户系统中 Chrome 的安装路径、user_data_dir、profile 列表。

服务于 baidu_keyword.py 的 native mode：跑监控前需要知道用户 Chrome 在哪、
用哪个 profile。所有探测都是 best-effort —— 失败时返回 None，UI 端会让用户
手动填路径。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROFILE_DIR_RE = re.compile(r"^(Default|Profile \d+)$")


# ── Chrome executable ────────────────────────────────────────────
def find_chrome_executable() -> str | None:
    """探测 chrome.exe 绝对路径。失败返回 None。

    顺序：注册表 → 默认安装路径（HKLM Program Files / Program Files (x86)）
    """
    p = _read_registry_chrome_path()
    if p:
        return p
    return _find_default_install_path()


def _read_registry_chrome_path() -> str | None:
    """读注册表 HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe
    的 (Default) 值。Windows-only；其他平台直接返回 None。
    """
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            if value and os.path.exists(value):
                return value
    except (OSError, FileNotFoundError) as e:
        logger.debug("registry chrome path lookup failed: %s", e)
        return None
    return None


def _find_default_install_path() -> str | None:
    """fallback 到默认安装路径。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    logger.debug("no chrome.exe at default install paths")
    return None


# ── User Data directory ──────────────────────────────────────────
def find_user_data_dir() -> str | None:
    """探测 Chrome User Data 目录绝对路径。默认 %LOCALAPPDATA%\\Google\\Chrome\\User Data。"""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    p = Path(local_appdata) / "Google" / "Chrome" / "User Data"
    if p.is_dir():
        return str(p)
    return None


# ── Profile 列表 ──────────────────────────────────────────────────
def list_profiles(user_data_dir: str) -> list[dict[str, Any]]:
    """扫 user_data_dir 下所有 profile 子目录，读各自 Preferences JSON 拿账号 email。

    Returns:
        list of {"name": str, "account_email": str | None}
        无 Preferences 或 JSON 无 account_info → email=None。
        非 profile 目录（Crashpad / ShaderCache / etc）会被过滤。
    """
    base = Path(user_data_dir)
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not _PROFILE_DIR_RE.match(entry.name):
            continue
        email = _read_account_email(entry / "Preferences")
        out.append({"name": entry.name, "account_email": email})
    return out


def _read_account_email(preferences_path: Path) -> str | None:
    """从 Preferences JSON 读第一个 account_info[0].email。失败返回 None。"""
    try:
        raw = preferences_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        accounts = data.get("account_info") or []
        if accounts and isinstance(accounts, list):
            email = accounts[0].get("email")
            if email and isinstance(email, str):
                return email
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.debug("read account_email failed: %s", e)
        return None
    return None
