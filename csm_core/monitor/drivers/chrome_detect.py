"""探测用户系统中 Chrome 的安装路径、user_data_dir、profile 列表。

服务于 baidu_keyword.py 的 native mode：跑监控前需要知道用户 Chrome 在哪、
用哪个 profile。所有探测都是 best-effort —— 失败时返回 None，UI 端会让用户
手动填路径。
"""
from __future__ import annotations

import errno
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
# User Data 所在渠道目录 → 该渠道的安装子目录。用于把 exe 和数据目录配对。
_CHANNEL_APP_DIRS: dict[str, tuple[str, ...]] = {
    "Chrome": ("Google", "Chrome"),
    "Chrome Beta": ("Google", "Chrome Beta"),
    "Chrome Dev": ("Google", "Chrome Dev"),
    "Chrome SxS": ("Google", "Chrome SxS"),
    "Chromium": ("Chromium",),
}


def find_chrome_executable(user_data_dir: str | None = None) -> str | None:
    """探测 chrome.exe 绝对路径。失败返回 None。

    顺序：同渠道安装目录（给定 user_data_dir 且非稳定版时）→ 注册表
    → 默认安装路径（Program Files / Program Files (x86) / %LOCALAPPDATA%）。

    为什么要配对渠道：数据目录探测覆盖了 Beta / Dev / Canary / Chromium，
    而注册表 App Paths\\chrome.exe 只认稳定版。拿 Beta 的 profile 副本去开
    稳定版 Chrome，Chrome 会以"配置文件来自更新版本"拒绝启动 —— 而且这个
    错误要等到「测试启动 / 登录副本」才冒出来，离导入很远，很难联想。
    """
    channel = _channel_app_dir_of(user_data_dir)
    if channel and channel != _CHANNEL_APP_DIRS["Chrome"]:
        paired = _find_channel_install_path(channel)
        if paired:
            return paired
        # 同渠道 exe 找不到就退回通用探测：有个能跑的总比没有强，
        # 而且设置页里可以手填。
    p = _read_registry_chrome_path()
    if p:
        return p
    return _find_default_install_path()


def _channel_app_dir_of(user_data_dir: str | None) -> tuple[str, ...] | None:
    """从 User Data 路径反推渠道安装子目录；不是标准布局（如组策略自定义目录）→ None。"""
    if not user_data_dir:
        return None
    p = Path(user_data_dir)
    if p.name != "User Data":
        return None
    return _CHANNEL_APP_DIRS.get(p.parent.name)


def _find_channel_install_path(app_dir: tuple[str, ...]) -> str | None:
    """在 Program Files / (x86) / %LOCALAPPDATA% 下找该渠道的 chrome.exe。"""
    roots = (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    for root in roots:
        if not root:
            continue
        cand = Path(root).joinpath(*app_dir, "Application", "chrome.exe")
        if cand.is_file():
            return str(cand)
    return None


def normalize_user_path(raw: str) -> str:
    """规整用户手填 / 粘贴的路径：去首尾空白与引号、展开 %VAR% 和 ~。

    资源管理器的「复制文件地址」给的是带引号的路径，帮助文案里又常写
    %LOCALAPPDATA%\\… —— 不规整就会 is_dir() 失败，把人引到"Chrome 是不是
    没装"上去，而真正的问题只是两个引号。
    """
    p = raw.strip().strip('"').strip("'").strip()
    if not p:
        return ""
    # 只在真出现 %VAR% 形态时才展开 —— expandvars 会把路径里的字面 %% 吃成 %
    if re.search(r"%[^%]+%", p):
        p = os.path.expandvars(p)
    return os.path.expanduser(p)


def can_list_profiles(user_data_dir: str) -> bool:
    """目录是否存在且能枚举。

    用来把「目录里没有 profile」和「目录读不动」分开 —— 后者在公司机
    （ACL / 重定向到网络盘 / 杀软占用）上会发生，报"请先启动一次 Chrome"
    是错的诊断，而且上层若把它当"路径失效"就会悄悄改用别的目录去复制。
    """
    base = Path(user_data_dir) if user_data_dir else None
    if base is None or not base.is_dir():
        return False
    try:
        next(iter(base.iterdir()), None)
    except OSError as e:
        logger.info("can_list_profiles: 无法枚举 %s（%s）", base, e)
        return False
    return True


def executable_matches_user_data_dir(exe_path: str | None, user_data_dir: str | None) -> bool:
    """已配置的 chrome.exe 与数据目录是否同一渠道。判断不了时返回 True。

    判断不了（组策略自定义目录、非常规安装路径）就当配套 —— 宁可不管，
    也不要拿一个猜的结论去覆盖用户手填的路径。
    """
    channel = _channel_app_dir_of(user_data_dir)
    if not channel or not exe_path:
        return True
    wanted = channel[-1].lower()
    parts = [p.lower() for p in Path(exe_path).parts]
    if wanted in parts:
        return True
    # exe 落在别的已知渠道目录下 → 明确不配套；都不认识 → 不下结论
    known = {d[-1].lower() for d in _CHANNEL_APP_DIRS.values()}
    return not known.intersection(parts)


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
# 各渠道 User Data 的默认位置（相对 %LOCALAPPDATA%），顺序即优先级。
_USER_DATA_REL_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("Google", "Chrome", "User Data"),
    ("Google", "Chrome Beta", "User Data"),
    ("Google", "Chrome Dev", "User Data"),
    ("Google", "Chrome SxS", "User Data"),  # Canary
    ("Chromium", "User Data"),
)

# Chrome 组策略路径变量 → 环境变量。公司统一部署的 Chrome 常用
# UserDataDir 策略把数据目录挪到别处（甚至网络盘）。
_POLICY_VAR_ENV: dict[str, str] = {
    "${local_app_data}": "LOCALAPPDATA",
    "${roaming_app_data}": "APPDATA",
    "${profile}": "USERPROFILE",
    "${user_name}": "USERNAME",
    "${program_files}": "ProgramFiles",
    "${windows}": "SystemRoot",
}

_CHROME_POLICY_KEY = r"SOFTWARE\Policies\Google\Chrome"


def _expand_policy_vars(raw: str) -> str | None:
    """展开策略值里的 ${...} 变量和 %VAR%。展不开（变量为空）→ None（不瞎猜）。"""
    out = raw.strip().strip('"')
    if not out:
        return None
    if "${documents}" in out:
        home = os.environ.get("USERPROFILE")
        if not home:
            return None
        out = out.replace("${documents}", str(Path(home) / "Documents"))
    for var, env_name in _POLICY_VAR_ENV.items():
        if var in out:
            val = os.environ.get(env_name)
            if not val:
                return None
            out = out.replace(var, val)
    return os.path.expandvars(out)


def _read_registry_user_data_dir() -> str | None:
    """读组策略 UserDataDir（HKLM 优先，再 HKCU）。非 Windows / 无策略 → None。"""
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, _CHROME_POLICY_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "UserDataDir")
        except (OSError, FileNotFoundError) as e:
            logger.debug("policy UserDataDir lookup failed (hive=%r): %s", hive, e)
            continue
        if not isinstance(value, str):
            continue
        expanded = _expand_policy_vars(value)
        if expanded and os.path.isdir(expanded):
            return expanded
    return None


def find_user_data_dir() -> str | None:
    """探测 Chrome User Data 目录绝对路径。找不到任何候选 → None。

    优先级：组策略 UserDataDir → %LOCALAPPDATA% 下各渠道默认位置
    （稳定版 → Beta → Dev → Canary → Chromium）。

    **同一批候选里「真的有 profile 的目录」赢**：Chrome 装了从没启动过、
    或者用户日常用的是 Beta/Canary 时，默认位置的 User Data 会存在但空无
    一物；直接返回它会让后续复制撞「找不到 Default」而无从下手。全都没
    profile 时才退回第一个存在的目录 —— 这样报错信息仍能指名道姓。
    """
    candidates: list[Path] = []
    policy_dir = _read_registry_user_data_dir()
    if policy_dir:
        candidates.append(Path(policy_dir))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        base = Path(local_appdata)
        candidates.extend(base.joinpath(*rel) for rel in _USER_DATA_REL_CANDIDATES)

    existing = [p for p in candidates if p.is_dir()]
    for p in existing:
        if list_profiles(str(p)):
            return str(p)
    return str(existing[0]) if existing else None


# ── Profile 列表 ──────────────────────────────────────────────────
def list_profiles(user_data_dir: str) -> list[dict[str, Any]]:
    """扫 user_data_dir 下所有 profile 子目录，读各自 Preferences JSON 拿账号信息。

    Returns:
        list of {"name": str, "account_email": str | None, "display_name": str | None}
        name = 目录名（"Default" / "Profile 1"）；display_name = 用户在 Chrome
        里给这个 profile 起的名字（"工作" / "个人"）—— 选 profile 时只看
        "Profile 1" 用户根本认不出是哪个。
        无 Preferences 或字段缺失 → 对应值为 None。
        非 profile 目录（Crashpad / ShaderCache / etc）会被过滤。
    """
    base = Path(user_data_dir)
    if not base.is_dir():
        return []
    try:
        entries = sorted(base.iterdir())
    except OSError as e:
        # 目录能 stat 但列不动（公司机 ACL / 网络重定向的 AppData / AV 占用）。
        # 探测一律 best-effort：当成没有 profile，绝不把异常抛给 HTTP 层。
        logger.info("list_profiles: 无法枚举 %s（%s）", base, e)
        return []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        if not _PROFILE_DIR_RE.match(entry.name):
            continue
        prefs = _read_preferences(entry / "Preferences")
        out.append({
            "name": entry.name,
            "account_email": _account_email_from(prefs),
            "display_name": _display_name_from(prefs),
        })
    return out


def resolve_profile_name(
    user_data_dir: str,
    preferred: str | None = None,
    profiles: list[dict[str, Any]] | None = None,
) -> str | None:
    """挑一个**目录里真实存在**的 profile 名。一个都没有 → None。

    写死 "Default" 是导入失败的根因：Chrome 用户在设置里删掉默认 profile 后
    只剩 "Profile 1"/"Profile 2"，`<User Data>\\Default` 根本不存在。

    顺序：
      1. preferred（用户在设置里选过的）—— 仅当它真的存在
      2. "Default" —— 绝大多数机器的日常 profile，保持老行为不变
      3. Local State 里的 profile.last_used —— Chrome 上次活跃的那个
      4. 只有一个 profile → 就它
      5. info_cache.active_time 最新的那个（并列时取排序后的第一个，保证确定性）

    profiles 传入已经扫好的 list_profiles 结果可省一次目录扫描（每个 profile
    的 Preferences 动辄几 MB，调用方往往刚扫过）。
    """
    names = [p["name"] for p in (profiles if profiles is not None else list_profiles(user_data_dir))]
    if not names:
        return None
    if preferred and preferred in names:
        return preferred
    if "Default" in names:
        return "Default"
    state = _read_local_state(user_data_dir)
    last_used = state.get("last_used")
    if isinstance(last_used, str) and last_used in names:
        return last_used
    if len(names) == 1:
        return names[0]
    active = state.get("active_times") or {}
    return max(names, key=lambda n: _as_float(active.get(n)))


def _as_float(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _read_local_state(user_data_dir: str) -> dict[str, Any]:
    """从 Local State 读 profile.last_used 和各 profile 的 active_time。

    读不到 / 坏 JSON → 空 dict（调用方退化到确定性兜底，不抛）。
    """
    path = Path(user_data_dir) / "Local State"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.debug("read Local State failed (%s): %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    profile = data.get("profile")
    if not isinstance(profile, dict):
        return {}
    info_cache = profile.get("info_cache")
    active_times: dict[str, Any] = {}
    if isinstance(info_cache, dict):
        for name, info in info_cache.items():
            if isinstance(info, dict):
                active_times[name] = info.get("active_time")
    return {"last_used": profile.get("last_used"), "active_times": active_times}


# ── B' profile copy ──────────────────────────────────────────────
def _profile_missing_error(source_root: Path, name: str) -> FileNotFoundError:
    """按「到底缺什么」生成给用户看的中文错误。

    这条错误会原样显示在设置页上 —— 必须说清是哪种情况、下一步做什么。
    老版本只抛英文 "source profile not found: …\\Default"，删过默认 profile
    的机器（只剩 Profile 1）看到它完全无从下手。
    """
    if not source_root.is_dir():
        return FileNotFoundError(
            f"Chrome 数据目录不存在：{source_root}。"
            "请确认 Chrome 已安装并至少正常启动过一次；"
            "如果你的 Chrome 数据不在默认位置（公司统一部署 / 换过盘），"
            "请在设置里手动填写「Chrome 数据目录」"
            "（形如 C:\\Users\\<用户名>\\AppData\\Local\\Google\\Chrome\\User Data）。"
        )
    if not can_list_profiles(str(source_root)):
        # 目录在、但列不动（权限 / 网络盘断了 / 杀软占用）。跟"空目录"必须分开说，
        # 否则会让天天在用 Chrome 的人去"先启动一次 Chrome"。
        return FileNotFoundError(
            f"没有权限读取 Chrome 数据目录：{source_root}。"
            "请确认当前 Windows 账号对该目录有读取权限（公司统一管理的电脑、"
            "或数据目录被重定向到网络盘时常见），或改用另一个数据目录。"
        )
    available = [p["name"] for p in list_profiles(str(source_root))]
    if available:
        return FileNotFoundError(
            f"Chrome 数据目录 {source_root} 里没有名为「{name}」的 profile。"
            f"该目录下可用的 profile：{'、'.join(available)}。"
            "请在设置里的「要复制的 Chrome profile」中改选一个后重新导入。"
        )
    # 常见误填：把报错里的 …\\User Data\\Default 原样粘回来，多填了一层。
    # 此时提示"先启动一次 Chrome"是错的（人家刚启动过）。
    if _PROFILE_DIR_RE.match(source_root.name) or (source_root / "Preferences").exists():
        return FileNotFoundError(
            f"{source_root} 看着像某个 profile 目录本身，你可能多填了一层。"
            f"「Chrome 数据目录」要填到 User Data 这一层，也就是它的上一级："
            f"{source_root.parent}。"
        )
    return FileNotFoundError(
        f"Chrome 数据目录 {source_root} 里没有任何 Chrome profile"
        "（Default / Profile 1 … 都不存在）。"
        "常见原因：Chrome 装了但从没启动过、日常用的是别的浏览器、"
        "或当前 Windows 账号不是你平时用 Chrome 的那个账号。"
        "请先正常启动一次 Chrome 并登录百度，再回来重新导入；"
        "数据目录不在默认位置的话，可在设置里手动填写「Chrome 数据目录」。"
    )


def _guard_not_self_copy(source_root: Path, target: Path) -> None:
    """源和副本目录重叠时直接拒绝 —— copy_profile_to 上来就 rmtree(target)。

    设置页把副本路径显示在「Chrome 数据目录」输入框附近，用户完全可能把它
    粘进去；而副本的内层目录恰好也叫 Default，profile 检查还会通过。真跑下去
    就是把自己十几 GB 的副本连同副本里的百度登录态一起删掉。
    """
    try:
        src = source_root.resolve()
        tgt = target.resolve()
    except OSError as e:  # 路径解析不了就不拦（后面自然会报目录不存在）
        logger.debug("self-copy guard: resolve failed: %s", e)
        return
    if src == tgt or src.is_relative_to(tgt) or tgt.is_relative_to(src):
        raise ValueError(
            f"「Chrome 数据目录」({source_root}) 和 CSM 的副本目录 ({target}) 是同一个"
            "（或互相嵌套），这样会把副本本身删掉。请把它改回你日常 Chrome 的 "
            "User Data 目录，或留空让程序自动探测。"
        )


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
    # 空路径要单独挡：Path("") 是当前工作目录，is_dir() 为 True，会让下面的
    # 诊断走进"目录里没有 profile"这条错误分支，报出一个 "." 让人莫名其妙。
    if not (source_user_data_dir or "").strip():
        raise FileNotFoundError(
            "没有指定 Chrome 数据目录。请在设置页点「检测 profile」重新探测，"
            "或手动填写 Chrome 的 User Data 目录。"
        )

    source_root = Path(source_user_data_dir)
    source_profile = source_root / source_profile_name
    # profile 名只接受 Chrome 真实的目录名（Default / Profile N）：一来兜底
    # 逻辑之外的脏值（""、"../x"）不该被当 profile 复制，二来空名会让
    # Path(dir) / "" == Path(dir)，把整个 User Data 当成一个 profile。
    if not _PROFILE_DIR_RE.match(source_profile_name or "") or not source_profile.is_dir():
        raise _profile_missing_error(source_root, source_profile_name)

    target = Path(target_path)
    _guard_not_self_copy(source_root, target)
    # 清旧 ── ignore_errors=True 之前用过会让 leveldb 文件锁残留 + mkdir
    # 撞 WinError 183。改成 raise 让 caller 看到清晰错误（"请关 Chrome
    # 进程再重试"），mkdir 加 exist_ok=True 容忍轻微残留。
    if target.exists():
        try:
            shutil.rmtree(target)
        except OSError as e:
            if getattr(e, "errno", None) == errno.ENOSPC:
                raise OSError(
                    f"磁盘空间不足，无法清理旧副本目录：{target}. 请清理磁盘后重试. 原因: {e}"
                ) from e
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
    # 磁盘满不是"文件被锁"——若当成锁吞掉，ENOSPC 会让每个文件都 skip、最后误报
    # 「Chrome 正在运行，关掉重试」。用标志位记下，复制后统一抛明确的磁盘满错误。
    disk_full = {"hit": False}

    def _resilient_copy(src: str, dst: str) -> None:
        try:
            shutil.copy2(src, dst)
        except (PermissionError, OSError) as e:
            if getattr(e, "errno", None) == errno.ENOSPC:
                disk_full["hit"] = True
            skipped_locked.append(os.path.basename(src))
            logger.info("copy_profile_to: 跳过文件 %s（%s）", src, e)

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
            if getattr(e, "errno", None) == errno.ENOSPC:
                disk_full["hit"] = True
            skipped_locked.append("Local State")
            logger.info("copy_profile_to: 跳过 Local State（%s）", e)

    # 磁盘满：致命且与"Chrome 开着"无关，抛明确错误让上层如实提示（而不是
    # 把满盘伪装成"文件被锁、请关 Chrome"让用户白关一遍还是失败）。
    if disk_full["hit"]:
        raise OSError(
            f"磁盘空间不足，无法完整复制 Chrome 副本到 {target}. 请清理磁盘后重试."
        )

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


def _read_preferences(preferences_path: Path) -> dict[str, Any]:
    """读 profile 的 Preferences JSON。文件缺失 / 坏 JSON / root 非 dict → {}。"""
    try:
        data = json.loads(preferences_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.debug("read Preferences failed (%s): %s", preferences_path, e)
        return {}
    return data if isinstance(data, dict) else {}


def _account_email_from(prefs: dict[str, Any]) -> str | None:
    """Preferences → account_info[0].email。缺失 / 脏数据 → None。"""
    accounts = prefs.get("account_info")
    if isinstance(accounts, list) and accounts and isinstance(accounts[0], dict):
        email = accounts[0].get("email")
        if isinstance(email, str) and email:
            return email
    return None


def _display_name_from(prefs: dict[str, Any]) -> str | None:
    """Preferences → profile.name（用户给 profile 起的显示名）。缺失 → None。"""
    profile = prefs.get("profile")
    if isinstance(profile, dict):
        name = profile.get("name")
        if isinstance(name, str) and name.strip():
            return name
    return None
