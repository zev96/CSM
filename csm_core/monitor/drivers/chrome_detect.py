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
    # Chrome 音视频缓冲缓存，已知会持续变大（纯缓存、无登录态）。
    "Media Cache",
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

# Chrome / leveldb 运行时锁哨兵文件。用户日常 Chrome 开着时这些被独占锁住，
# copy 必然 [Errno 13] Permission denied —— 但它们要么是 0 字节占位、要么下次
# 启动自动重建，**复制到副本反而有害**（残留锁会让副本 Chromium 误判被占）。
# 按名跳过，跟缓存目录同机制。
_PROFILE_RUNTIME_LOCK_NAMES = frozenset({
    "LOCK",
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "lockfile",
})

# 这些文件被锁住没复制成功 = 登录态没带过来。不致命（用户可在副本里重登），
# 但值得给一条 warning 让用户知道要么关 Chrome 重导、要么登录副本。
_PROFILE_LOGIN_FILE_NAMES = frozenset({
    "Cookies",
    "Cookies-journal",
})


def _copy_ignore_caches(dir_path: str, names: list[str]) -> list[str]:
    """shutil.copytree ignore callback：跳过 Chrome cache 子目录 + 运行时锁文件。"""
    return [
        n for n in names
        if n in _PROFILE_CACHE_DIRS_TO_SKIP or n in _PROFILE_RUNTIME_LOCK_NAMES
    ]


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
          skipped_locked: list[str] —— 因被锁跳过的文件名（Chrome 开着时常见）
          warning: str | None —— 登录态文件被锁时的用户提示，否则 None
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

    # 逐文件容错复制 —— 用户日常 Chrome 通常**正开着**（这功能就是为「复制日常
    # profile」设计的），Network\Cookies / 各 leveldb LOCK 等文件被独占锁住。
    # 原来的裸 shutil.copytree 是"全有或全无"：任一文件 PermissionError 都会在
    # 最后一次性抛 shutil.Error，把整次导入判失败（即便 99% 文件已复制成功）。
    # 这里换成 copy_function 吞掉单文件锁错误并记录，让复制整体成功；登录态
    # 文件（Cookies）被锁则回一条 warning，让上层提示用户而不是报红「复制失败」。
    skipped_locked: list[str] = []

    def _resilient_copy(src: str, dst: str) -> None:
        try:
            shutil.copy2(src, dst)
        except (PermissionError, OSError) as e:
            skipped_locked.append(os.path.basename(src))
            logger.info("copy_profile_to: 跳过被锁文件 %s（%s）", src, e)

    # 复制 profile 内容 → target/Default/
    target_profile = target / "Default"
    try:
        shutil.copytree(
            source_profile,
            target_profile,
            ignore=_copy_ignore_caches,
            copy_function=_resilient_copy,
        )
    except shutil.Error as e:
        # copy_function 已吞掉单文件错误；残留的 shutil.Error 只可能是目录级
        # copystat 噪声 —— 记日志继续，不让它把整次导入判失败。
        logger.info("copy_profile_to: 忽略 copytree 残留错误：%s", e)

    # 复制 Local State（如果存在）── Chrome 解密 cookie 必需。同样容错。
    source_local_state = Path(source_user_data_dir) / "Local State"
    if source_local_state.is_file():
        try:
            shutil.copy2(source_local_state, target / "Local State")
        except (PermissionError, OSError) as e:
            skipped_locked.append("Local State")
            logger.info("copy_profile_to: 跳过被锁 Local State（%s）", e)

    elapsed = time.monotonic() - start
    size_bytes = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())

    # 登录态文件被锁 → 给一条 warning（不致命）。Local State 缺失也会让带过来的
    # 加密 Cookie 无法解密，等价于登录态没过来，一并纳入提示。
    login_locked = [n for n in skipped_locked if n in _PROFILE_LOGIN_FILE_NAMES]
    warning: str | None = None
    if login_locked or "Local State" in skipped_locked:
        warning = (
            "检测到 Chrome 正在运行，登录态（Cookies）未能复制到副本。"
            "要么完全关闭 Chrome（含后台进程）后再点「重新导入」，"
            "要么直接点「登录百度（副本）」在副本里重新登录百度。"
        )
    return {
        "imported_at": datetime.utcnow().isoformat(),
        "size_mb": round(size_bytes / 1024 / 1024, 1),
        "elapsed_s": round(elapsed, 1),
        "skipped_locked": skipped_locked,
        "warning": warning,
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
