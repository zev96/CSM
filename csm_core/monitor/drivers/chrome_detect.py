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
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROFILE_DIR_RE = re.compile(r"^(Default|Profile \d+)$")

# Chrome 各种 cache / runtime 子目录 ── 占空间不影响登录态/书签/history
_PROFILE_CACHE_DIRS_TO_SKIP = frozenset({
    "Cache",
    "Code Cache",
    "GPUCache",
    "Service Worker",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "ShaderCache",
    "GrShaderCache",
    "Application Cache",
    "blob_storage",
    "File System",
    "VideoDecodeStats",
    "Storage",
    "Crashpad",
    "PnaclTranslationCache",
    # Cache Storage API 数据（Service Worker\CacheStorage、WebStorage\<bucket>\CacheStorage）
    # —— 永远是缓存的 HTTP 响应，不含 cookie / 登录态
    "CacheStorage",
    # 压缩字典缓存
    "Shared Dictionary",
    # extension caches，不影响扩展功能
    "Extension State",
    "Extension Cookies-journal",
    # 老 IndexedDB / leveldb 可能很大但不影响百度登录态
    # 保留 IndexedDB （某些站登录态依赖）── 不在这里排除
})


def _copy_ignore_caches(dir_path: str, names: list[str]) -> list[str]:
    """shutil.copytree ignore callback：跳过 Chrome cache 子目录。"""
    return [n for n in names if n in _PROFILE_CACHE_DIRS_TO_SKIP]


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
    """读注册表 App Paths\\chrome.exe 的 (Default) 值。Windows-only；其他平台返回 None。

    先查 HKLM（全机器安装），再查 HKCU（仅当前用户安装 —— 公司机无管理员权限时
    Chrome 常装到 %LOCALAPPDATA% 并只写 HKCU）。任一 hive 的值指向不存在的文件
    （卸载残留）时跳过，继续查下一个。
    """
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None
    sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, sub_key) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value and os.path.exists(value):
                    return value
        except (OSError, FileNotFoundError) as e:
            logger.debug("registry chrome path lookup failed (hive=%r): %s", hive, e)
            continue
    return None


def _find_default_install_path() -> str | None:
    """fallback 到默认安装路径。含 per-user 安装位置（%LOCALAPPDATA%）。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    # per-user 安装（无管理员权限时 Chrome 装到这里）
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(
            str(Path(local_appdata) / "Google" / "Chrome" / "Application" / "chrome.exe")
        )
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


# ── B' profile copy ──────────────────────────────────────────────
def copy_profile_to(
    source_user_data_dir: str,
    source_profile_name: str,
    target_path: str,
) -> dict[str, Any]:
    """复制 Chrome profile 到 CSM 专用目录（B' 方案）。

    流程：
    1. 删除 target_path 下旧副本（如有）
    2. cp 整个 <source_user_data_dir>/<source_profile_name>/ 到 <target_path>/Default/
       注意：内层目录必须叫 'Default'，让 launch_persistent_context 的
       --profile-directory=Default 能找到（user_data_dir = target_path）
    3. 复制 source_user_data_dir 下的 "Local State" 文件到 target_path/
       （Chrome encrypted password store 引用 Local State 的 encryption_key）

    Args:
        source_user_data_dir: 用户 Chrome User Data 目录绝对路径
        source_profile_name: "Default" / "Profile 1" 等
        target_path: 副本目标目录（通常 <config_dir>/baidu_chrome_profile_copy/）

    Returns:
        dict with keys:
          imported_at: ISO8601 时间戳
          size_mb: 副本大小（MB）
          elapsed_s: 复制耗时
    """
    source_profile = Path(source_user_data_dir) / source_profile_name
    if not source_profile.is_dir():
        raise FileNotFoundError(f"source profile not found: {source_profile}")

    target = Path(target_path)
    # 清旧 ── ignore_errors=True 之前用过会让 leveldb 文件锁残留 + mkdir
    # 撞 WinError 183。改成 raise 让 caller 看到清晰错误（"请关 Chrome
    # 进程再重试"），mkdir 加 exist_ok=True 容忍轻微残留。
    if target.exists():
        try:
            shutil.rmtree(target)
        except OSError as e:
            raise OSError(
                f"旧副本目录无法清空（可能有 Chromium / Chrome 进程占着文件锁）："
                f"{target}. 请关掉所有 Chrome / Chromium 进程后重试，"
                f"或手动删除该目录. 原因: {e}"
            ) from e
    target.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()

    # 复制 profile 内容 → target/Default/
    target_profile = target / "Default"
    shutil.copytree(source_profile, target_profile, ignore=_copy_ignore_caches)

    # 复制 Local State（如果存在）── Chrome 解密 cookie 必需
    source_local_state = Path(source_user_data_dir) / "Local State"
    if source_local_state.is_file():
        shutil.copy2(source_local_state, target / "Local State")

    elapsed = time.monotonic() - start
    size_bytes = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    return {
        "imported_at": datetime.utcnow().isoformat(),
        "size_mb": round(size_bytes / 1024 / 1024, 1),
        "elapsed_s": round(elapsed, 1),
    }


def _path_size(path: Path) -> int:
    """递归累加目录下所有文件字节数；读不到的项跳过。"""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def prune_profile_caches(profile_copy_path: str) -> dict[str, Any]:
    """删除副本里的 Chrome 缓存目录 / 文件，保留登录态与用户数据。

    与 copy_profile_to 的 _copy_ignore_caches 语义对称：删除任意层级下
    名字在 _PROFILE_CACHE_DIRS_TO_SKIP 里的目录 / 文件。best-effort ——
    逐项 try/except，被锁的项跳过，整体永不抛异常（调用方在 session
    finally 里，fetch 已完成，清理失败不能影响结果）。

    Args:
        profile_copy_path: 副本根目录（<config_dir>/baidu_chrome_profile_copy）。

    Returns:
        {"freed_mb": float, "elapsed_s": float}。路径不存在 → 全 0。
    """
    base = Path(profile_copy_path)
    if not base.is_dir():
        return {"freed_mb": 0.0, "elapsed_s": 0.0}

    start = time.monotonic()
    freed = 0
    for root, dirs, files in os.walk(base, topdown=True):
        root_path = Path(root)
        # 删匹配的文件（如 Extension Cookies-journal）
        for fname in files:
            if fname in _PROFILE_CACHE_DIRS_TO_SKIP:
                fp = root_path / fname
                try:
                    freed += fp.stat().st_size
                    fp.unlink()
                except OSError as e:
                    logger.debug("prune unlink failed %s: %s", fp, e)
        # 删匹配的目录，并从遍历里剔除（不再下探）
        keep = []
        for d in dirs:
            if d in _PROFILE_CACHE_DIRS_TO_SKIP:
                dp = root_path / d
                try:
                    freed += _path_size(dp)
                    shutil.rmtree(dp, ignore_errors=True)
                except OSError as e:
                    logger.debug("prune rmtree failed %s: %s", dp, e)
            else:
                keep.append(d)
        dirs[:] = keep

    elapsed = time.monotonic() - start
    return {"freed_mb": round(freed / 1024 / 1024, 1), "elapsed_s": round(elapsed, 1)}


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
