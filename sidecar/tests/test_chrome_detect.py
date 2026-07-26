"""chrome_detect.py 单元测试 —— mock 注册表 / 文件系统 / Preferences JSON。"""
from __future__ import annotations

import os

import pytest

from csm_core.monitor.drivers import chrome_detect


# ── find_chrome_executable ───────────────────────────────────────
class TestFindChromeExecutable:
    def test_returns_registry_path_when_present(self, monkeypatch):
        """注册表查到 → 直接返回，不查文件系统。"""
        fake_path = r"C:\Custom\Chrome\chrome.exe"
        monkeypatch.setattr(chrome_detect, "_read_registry_chrome_path", lambda: fake_path)
        # 文件系统探测应该不被调用 —— 用 monkeypatch 抛异常验证
        monkeypatch.setattr(
            chrome_detect, "_find_default_install_path",
            lambda: pytest.fail("不应回退到文件系统探测"),
        )
        assert chrome_detect.find_chrome_executable() == fake_path

    def test_falls_back_to_default_path_when_no_registry(self, monkeypatch, tmp_path):
        """注册表无 → 找默认安装路径。"""
        monkeypatch.setattr(chrome_detect, "_read_registry_chrome_path", lambda: None)
        fake_default = tmp_path / "chrome.exe"
        fake_default.touch()
        monkeypatch.setattr(chrome_detect, "_find_default_install_path", lambda: str(fake_default))
        assert chrome_detect.find_chrome_executable() == str(fake_default)

    def test_returns_none_when_both_fail(self, monkeypatch):
        """注册表 + 默认路径都没 → None。"""
        monkeypatch.setattr(chrome_detect, "_read_registry_chrome_path", lambda: None)
        monkeypatch.setattr(chrome_detect, "_find_default_install_path", lambda: None)
        assert chrome_detect.find_chrome_executable() is None


# ── _read_registry_chrome_path （HKLM 全机器 + HKCU 仅当前用户安装）──────
@pytest.mark.skipif(os.name != "nt", reason="winreg is Windows-only")
class TestReadRegistryChromePath:
    """per-user 安装（无管理员权限的公司机常见）chrome.exe 注册在 HKCU 而非 HKLM。"""

    def _patch_winreg(self, monkeypatch, *, hklm_value, hkcu_value):
        """装一个 fake winreg：HKLM/HKCU 各返回给定值；值为 None → OpenKey 抛 FileNotFoundError。"""
        import winreg

        class _FakeKey:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        values = {
            winreg.HKEY_LOCAL_MACHINE: hklm_value,
            winreg.HKEY_CURRENT_USER: hkcu_value,
        }

        def fake_open(hive, sub):
            v = values.get(hive)
            if v is None:
                raise FileNotFoundError("no such key")
            return _FakeKey(v)

        def fake_query(key, name):
            return (key.value, winreg.REG_SZ)

        monkeypatch.setattr(winreg, "OpenKey", fake_open)
        monkeypatch.setattr(winreg, "QueryValueEx", fake_query)

    def test_falls_back_to_hkcu_when_hklm_missing(self, monkeypatch, tmp_path):
        """HKLM 无键、HKCU 有 → 返回 HKCU 的路径。"""
        exe = tmp_path / "chrome.exe"
        exe.touch()
        self._patch_winreg(monkeypatch, hklm_value=None, hkcu_value=str(exe))
        assert chrome_detect._read_registry_chrome_path() == str(exe)

    def test_skips_hive_whose_path_does_not_exist(self, monkeypatch, tmp_path):
        """HKLM 值指向已卸载的残留路径（文件不存在）→ 跳到 HKCU。"""
        stale = tmp_path / "uninstalled" / "chrome.exe"  # 不创建
        exe = tmp_path / "chrome.exe"
        exe.touch()
        self._patch_winreg(monkeypatch, hklm_value=str(stale), hkcu_value=str(exe))
        assert chrome_detect._read_registry_chrome_path() == str(exe)

    def test_prefers_hklm_over_hkcu(self, monkeypatch, tmp_path):
        """全机器安装优先：HKLM 命中就不查 HKCU。"""
        hklm_exe = tmp_path / "hklm" / "chrome.exe"
        hklm_exe.parent.mkdir()
        hklm_exe.touch()
        hkcu_exe = tmp_path / "hkcu" / "chrome.exe"
        hkcu_exe.parent.mkdir()
        hkcu_exe.touch()
        self._patch_winreg(monkeypatch, hklm_value=str(hklm_exe), hkcu_value=str(hkcu_exe))
        assert chrome_detect._read_registry_chrome_path() == str(hklm_exe)

    def test_returns_none_when_neither_hive_has_key(self, monkeypatch):
        self._patch_winreg(monkeypatch, hklm_value=None, hkcu_value=None)
        assert chrome_detect._read_registry_chrome_path() is None


# ── _find_default_install_path （含 per-user %LOCALAPPDATA% 安装位置）────
class TestFindDefaultInstallPath:
    def test_includes_localappdata_per_user_install(self, monkeypatch, tmp_path):
        """per-user 安装 chrome.exe 落在 %LOCALAPPDATA%\\Google\\Chrome\\Application。"""
        local = tmp_path / "Local"
        exe = local / "Google" / "Chrome" / "Application" / "chrome.exe"
        exe.parent.mkdir(parents=True)
        exe.touch()
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        # 隔离：测试机可能真装了 Program Files Chrome，强制 exists 只认我们造的路径
        target = str(exe)
        monkeypatch.setattr(chrome_detect.os.path, "exists", lambda p: p == target)
        assert chrome_detect._find_default_install_path() == target

    def test_returns_none_when_no_candidate_exists(self, monkeypatch):
        monkeypatch.setattr(chrome_detect.os.path, "exists", lambda p: False)
        assert chrome_detect._find_default_install_path() is None


# ── find_user_data_dir ───────────────────────────────────────────
class TestFindUserDataDir:
    def test_returns_localappdata_default(self, monkeypatch, tmp_path):
        fake_local = tmp_path / "AppData" / "Local"
        chrome_data = fake_local / "Google" / "Chrome" / "User Data"
        chrome_data.mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        # 隔离：跑测试的机器本身可能设了 Chrome UserDataDir 组策略
        monkeypatch.setattr(chrome_detect, "_read_registry_user_data_dir", lambda: None)
        assert chrome_detect.find_user_data_dir() == str(chrome_data)

    def test_returns_none_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # 不创建 Google/Chrome
        monkeypatch.setattr(chrome_detect, "_read_registry_user_data_dir", lambda: None)
        assert chrome_detect.find_user_data_dir() is None


# ── find_user_data_dir 的兜底路径（非默认渠道 / 策略目录 / 空目录）────────
class TestFindUserDataDirFallbacks:
    """默认位置不是唯一真相：Chrome 装了没启动过（目录空）、只装了 Beta/Canary、
    公司电脑用组策略把数据目录改到别处 —— 这些机器上原来的单点探测会返回一个
    没有 profile 的目录，导入必然失败。"""

    @pytest.fixture(autouse=True)
    def _no_policy(self, monkeypatch):
        monkeypatch.setattr(chrome_detect, "_read_registry_user_data_dir", lambda: None)

    def test_prefers_dir_that_actually_has_profiles(self, monkeypatch, tmp_path):
        """稳定版目录存在但空 → 退到真的有 profile 的 Beta 目录。"""
        local = tmp_path / "Local"
        stable = local / "Google" / "Chrome" / "User Data"
        stable.mkdir(parents=True)  # 空目录：装了但从没启动过
        beta = local / "Google" / "Chrome Beta" / "User Data"
        (beta / "Profile 1").mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        assert chrome_detect.find_user_data_dir() == str(beta)

    def test_stable_channel_wins_when_both_have_profiles(self, monkeypatch, tmp_path):
        local = tmp_path / "Local"
        stable = local / "Google" / "Chrome" / "User Data"
        (stable / "Default").mkdir(parents=True)
        beta = local / "Google" / "Chrome Beta" / "User Data"
        (beta / "Default").mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        assert chrome_detect.find_user_data_dir() == str(stable)

    def test_falls_back_to_first_existing_dir_when_none_has_profiles(
        self, monkeypatch, tmp_path
    ):
        """全都没 profile → 仍返回默认目录（让上层报错能指名道姓，而不是
        变成"没检测到 Chrome"这种误导性提示）。"""
        local = tmp_path / "Local"
        stable = local / "Google" / "Chrome" / "User Data"
        stable.mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        assert chrome_detect.find_user_data_dir() == str(stable)

    def test_policy_dir_wins_over_default_location(self, monkeypatch, tmp_path):
        """组策略 UserDataDir 指定的目录（有 profile）优先于默认位置。"""
        local = tmp_path / "Local"
        stable = local / "Google" / "Chrome" / "User Data"
        (stable / "Default").mkdir(parents=True)
        policy = tmp_path / "D" / "ChromeData"
        (policy / "Default").mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setattr(
            chrome_detect, "_read_registry_user_data_dir", lambda: str(policy)
        )
        assert chrome_detect.find_user_data_dir() == str(policy)


# ── _expand_policy_vars （Chrome 策略路径变量）────────────────────
class TestExpandPolicyVars:
    def test_expands_local_app_data(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\bob\AppData\Local")
        out = chrome_detect._expand_policy_vars(r"${local_app_data}\Chrome\Data")
        assert out == r"C:\Users\bob\AppData\Local\Chrome\Data"

    def test_returns_none_when_var_unresolvable(self, monkeypatch):
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert chrome_detect._expand_policy_vars(r"${local_app_data}\X") is None

    def test_passes_through_plain_path(self):
        assert chrome_detect._expand_policy_vars(r"D:\ChromeData") == r"D:\ChromeData"

    def test_blank_returns_none(self):
        assert chrome_detect._expand_policy_vars("   ") is None


# ── resolve_profile_name ─────────────────────────────────────────
class TestResolveProfileName:
    """写死 "Default" 是这次 bug 的根因 —— 挑 profile 必须看目录里真有什么。"""

    def _local_state(self, user_data: "object", payload: str) -> None:
        (user_data / "Local State").write_text(payload, encoding="utf-8")

    def test_prefers_existing_preferred(self, tmp_path):
        for n in ("Default", "Profile 1"):
            (tmp_path / n).mkdir()
        assert chrome_detect.resolve_profile_name(
            str(tmp_path), preferred="Profile 1"
        ) == "Profile 1"

    def test_ignores_preferred_that_does_not_exist(self, tmp_path):
        (tmp_path / "Default").mkdir()
        assert chrome_detect.resolve_profile_name(
            str(tmp_path), preferred="Profile 7"
        ) == "Default"

    def test_falls_back_to_default(self, tmp_path):
        for n in ("Default", "Profile 1"):
            (tmp_path / n).mkdir()
        assert chrome_detect.resolve_profile_name(str(tmp_path)) == "Default"

    def test_uses_last_used_from_local_state_when_no_default(self, tmp_path):
        """没有 Default（用户删过默认 profile）→ 用 Local State 记的 last_used。"""
        for n in ("Profile 1", "Profile 3"):
            (tmp_path / n).mkdir()
        self._local_state(tmp_path, '{"profile":{"last_used":"Profile 3"}}')
        assert chrome_detect.resolve_profile_name(str(tmp_path)) == "Profile 3"

    def test_uses_single_profile_when_no_default(self, tmp_path):
        (tmp_path / "Profile 1").mkdir()
        assert chrome_detect.resolve_profile_name(str(tmp_path)) == "Profile 1"

    def test_uses_most_recently_active_when_no_signal(self, tmp_path):
        for n in ("Profile 1", "Profile 2"):
            (tmp_path / n).mkdir()
        self._local_state(
            tmp_path,
            '{"profile":{"info_cache":{"Profile 1":{"active_time":10},'
            '"Profile 2":{"active_time":99}}}}',
        )
        assert chrome_detect.resolve_profile_name(str(tmp_path)) == "Profile 2"

    def test_returns_none_when_no_profiles(self, tmp_path):
        (tmp_path / "Crashpad").mkdir()
        assert chrome_detect.resolve_profile_name(str(tmp_path)) is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        assert chrome_detect.resolve_profile_name(str(tmp_path / "nope")) is None

    def test_tolerates_corrupt_local_state(self, tmp_path):
        for n in ("Profile 1", "Profile 2"):
            (tmp_path / n).mkdir()
        self._local_state(tmp_path, "{not json")
        # 不抛，退化成确定性的第一个
        assert chrome_detect.resolve_profile_name(str(tmp_path)) == "Profile 1"


# ── list_profiles ────────────────────────────────────────────────
class TestListProfiles:
    def test_lists_default_and_numbered_profiles_with_account_emails(self, tmp_path):
        """枚举 Default / Profile 1 / Profile 2，从 Preferences JSON 读账号 email。"""
        # 准备测试数据
        for name, email in [("Default", "user1@gmail.com"), ("Profile 1", "user2@gmail.com")]:
            p = tmp_path / name
            p.mkdir()
            (p / "Preferences").write_text(
                '{"account_info":[{"email":"' + email + '"}]}',
                encoding="utf-8",
            )
        # 无 Preferences 的 profile —— 仍列出但 email=None
        (tmp_path / "Profile 2").mkdir()

        result = chrome_detect.list_profiles(str(tmp_path))
        names = {p["name"] for p in result}
        assert names == {"Default", "Profile 1", "Profile 2"}
        by_name = {p["name"]: p for p in result}
        assert by_name["Default"]["account_email"] == "user1@gmail.com"
        assert by_name["Profile 1"]["account_email"] == "user2@gmail.com"
        assert by_name["Profile 2"]["account_email"] is None

    def test_returns_empty_when_dir_missing(self):
        assert chrome_detect.list_profiles("/nonexistent/path") == []

    def test_reads_display_name_from_preferences(self, tmp_path):
        """用户在 Chrome 里给 profile 起的名字（"工作"/"个人"）—— 下拉里
        只显示 "Profile 1" 用户根本认不出该选哪个。"""
        p = tmp_path / "Profile 1"
        p.mkdir()
        (p / "Preferences").write_text(
            '{"profile":{"name":"\\u5de5\\u4f5c"}}', encoding="utf-8"
        )
        (tmp_path / "Profile 2").mkdir()  # 无 Preferences → display_name=None
        by_name = {x["name"]: x for x in chrome_detect.list_profiles(str(tmp_path))}
        assert by_name["Profile 1"]["display_name"] == "工作"
        assert by_name["Profile 2"]["display_name"] is None

    def test_ignores_non_profile_directories(self, tmp_path):
        """User Data 下有 Crashpad、ShaderCache 等非 profile 目录，要跳过。"""
        (tmp_path / "Default").mkdir()
        (tmp_path / "Crashpad").mkdir()
        (tmp_path / "ShaderCache").mkdir()
        names = {p["name"] for p in chrome_detect.list_profiles(str(tmp_path))}
        assert names == {"Default"}

    def test_list_profiles_handles_malformed_preferences_json(self, tmp_path):
        """Preferences 是合法 JSON 但 root 不是 dict（罕见但磁盘损坏可能产生）→
        不抛、返回 account_email=None。"""
        for name, content in [
            ("Default", "[]"),       # 根是 list 不是 dict
            ("Profile 1", "null"),   # 根是 null
            ("Profile 2", "42"),     # 根是数字
        ]:
            p = tmp_path / name
            p.mkdir()
            (p / "Preferences").write_text(content, encoding="utf-8")

        result = chrome_detect.list_profiles(str(tmp_path))
        assert len(result) == 3
        assert all(p["account_email"] is None for p in result)

    def test_list_profiles_handles_non_dict_account_entry(self, tmp_path):
        """account_info[0] 是 str 而不是 dict（脏数据）→ 不抛、email=None。"""
        p = tmp_path / "Default"
        p.mkdir()
        (p / "Preferences").write_text(
            '{"account_info": ["plain-string-not-dict"]}',
            encoding="utf-8",
        )
        result = chrome_detect.list_profiles(str(tmp_path))
        assert result[0]["account_email"] is None


# ── 探测链路的健壮性（不能因为一个目录读不动就整条挂掉）────────────
class TestProbesNeverRaise:
    """模块契约：探测都是 best-effort，失败返回空/None，绝不往上抛。

    回归 bug：find_user_data_dir 改成"看目录里有没有 profile"后会 iterdir()，
    而 Path.is_dir() 对"能 stat 但不让列目录"的目录返回 True（公司机 ACL /
    网络重定向 AppData 常见）→ PermissionError 直冒到 HTTP 500。
    """

    def test_list_profiles_survives_permission_error(self, tmp_path, monkeypatch):
        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(chrome_detect.Path, "iterdir", boom)
        assert chrome_detect.list_profiles(str(tmp_path)) == []

    def test_find_user_data_dir_survives_permission_error(self, monkeypatch, tmp_path):
        local = tmp_path / "Local"
        stable = local / "Google" / "Chrome" / "User Data"
        stable.mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setattr(chrome_detect, "_read_registry_user_data_dir", lambda: None)

        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(chrome_detect.Path, "iterdir", boom)
        # 列不动就当没 profile，仍返回该目录（让后续报错能指名道姓），不抛
        assert chrome_detect.find_user_data_dir() == str(stable)

    def test_resolve_profile_name_survives_permission_error(self, monkeypatch, tmp_path):
        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(chrome_detect.Path, "iterdir", boom)
        assert chrome_detect.resolve_profile_name(str(tmp_path)) is None


# ── 用户手填路径的规整 ────────────────────────────────────────────
class TestNormalizeUserPath:
    """资源管理器「复制文件地址」给的是带引号的路径，帮助文案里又常写 %VAR%。
    不规整就会得到「目录不存在」，把人引去查 Chrome 装没装。"""

    def test_strips_quotes_and_whitespace(self):
        assert chrome_detect.normalize_user_path('  "D:\\Chrome\\User Data" ') == r"D:\Chrome\User Data"

    def test_expands_env_vars(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\bob\AppData\Local")
        out = chrome_detect.normalize_user_path(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        assert out == r"C:\Users\bob\AppData\Local\Google\Chrome\User Data"

    def test_blank_stays_blank(self):
        assert chrome_detect.normalize_user_path('  ""  ') == ""

    def test_keeps_literal_double_percent(self):
        """没有 %VAR% 形态时别碰 % —— expandvars 会把 %% 吃成 %。"""
        assert chrome_detect.normalize_user_path(r"D:\a\b%%c") == r"D:\a\b%%c"


# ── 「没有 profile」 vs 「读不动」要分清 ──────────────────────────
class TestUnreadableDirDiagnosis:
    def test_can_list_profiles_false_when_unreadable(self, monkeypatch, tmp_path):
        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(chrome_detect.Path, "iterdir", boom)
        assert chrome_detect.can_list_profiles(str(tmp_path)) is False

    def test_can_list_profiles_true_for_empty_readable_dir(self, tmp_path):
        assert chrome_detect.can_list_profiles(str(tmp_path)) is True

    def test_can_list_profiles_false_when_missing(self, tmp_path):
        assert chrome_detect.can_list_profiles(str(tmp_path / "nope")) is False

    def test_error_says_permission_not_never_launched(self, monkeypatch, tmp_path):
        """目录读不动时报「没有任何 profile，请先启动一次 Chrome」是错的诊断 ——
        人家 Chrome 天天在用，问题是权限。"""
        user_data = tmp_path / "User Data"
        user_data.mkdir()

        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(chrome_detect.Path, "iterdir", boom)
        with pytest.raises(FileNotFoundError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="Default",
                target_path=str(tmp_path / "dest"),
            )
        msg = str(exc.value)
        assert "权限" in msg
        assert "从没启动过" not in msg


# ── exe 与数据目录的渠道是否配套 ──────────────────────────────────
class TestExecutableMatchesUserDataDir:
    def test_mismatch_when_stable_exe_with_beta_data_dir(self):
        assert chrome_detect.executable_matches_user_data_dir(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\U\AppData\Local\Google\Chrome Beta\User Data",
        ) is False

    def test_match_when_same_channel(self):
        assert chrome_detect.executable_matches_user_data_dir(
            r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
            r"C:\U\AppData\Local\Google\Chrome Beta\User Data",
        ) is True

    def test_stable_pair_matches(self):
        assert chrome_detect.executable_matches_user_data_dir(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\U\AppData\Local\Google\Chrome\User Data",
        ) is True

    def test_unknown_layout_is_treated_as_match(self):
        """组策略自定义目录判断不了渠道 —— 一律当配套，别乱改用户的设置。"""
        assert chrome_detect.executable_matches_user_data_dir(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"D:\CorpChromeData",
        ) is True

    def test_missing_exe_is_treated_as_match(self):
        assert chrome_detect.executable_matches_user_data_dir(
            "", r"C:\U\Google\Chrome Beta\User Data"
        ) is True


# ── 渠道配对：数据目录是 Beta 就别去开稳定版 chrome.exe ──────────────
class TestChannelPairedExecutable:
    def test_picks_beta_exe_for_beta_user_data_dir(self, monkeypatch, tmp_path):
        """用 Beta 的 profile 副本去开稳定版 Chrome 会被拒（配置来自更新版本）。"""
        pf = tmp_path / "Program Files"
        beta_exe = pf / "Google" / "Chrome Beta" / "Application" / "chrome.exe"
        beta_exe.parent.mkdir(parents=True)
        beta_exe.touch()
        monkeypatch.setenv("ProgramFiles", str(pf))
        monkeypatch.setattr(
            chrome_detect, "_read_registry_chrome_path", lambda: r"C:\stable\chrome.exe"
        )
        got = chrome_detect.find_chrome_executable(
            user_data_dir=r"C:\X\AppData\Local\Google\Chrome Beta\User Data"
        )
        assert got == str(beta_exe)

    def test_falls_back_to_generic_probe_when_channel_exe_missing(self, monkeypatch):
        monkeypatch.setattr(
            chrome_detect, "_read_registry_chrome_path", lambda: r"C:\stable\chrome.exe"
        )
        monkeypatch.setattr(chrome_detect, "_find_channel_install_path", lambda _d: None)
        got = chrome_detect.find_chrome_executable(
            user_data_dir=r"C:\X\Google\Chrome SxS\User Data"
        )
        assert got == r"C:\stable\chrome.exe"

    def test_stable_user_data_dir_uses_normal_probe(self, monkeypatch):
        monkeypatch.setattr(
            chrome_detect, "_read_registry_chrome_path", lambda: r"C:\stable\chrome.exe"
        )
        monkeypatch.setattr(
            chrome_detect, "_find_channel_install_path",
            lambda _d: pytest.fail("稳定版不该走渠道分支"),
        )
        assert chrome_detect.find_chrome_executable(
            user_data_dir=r"C:\X\Google\Chrome\User Data"
        ) == r"C:\stable\chrome.exe"


# ── copy_profile_to ───────────────────────────────────────────────
class TestCopyProfileTo:
    def _make_source(self, tmp_path, profile_name: str = "Default") -> tuple:
        """Create a minimal fake Chrome User Data dir with a profile + Local State."""
        user_data = tmp_path / "User Data"
        user_data.mkdir()
        profile = user_data / profile_name
        profile.mkdir()
        # A few fake files inside the profile
        (profile / "Cookies").write_bytes(b"fake-cookies-data-" * 100)
        (profile / "History").write_bytes(b"fake-history-data-" * 100)
        subdir = profile / "Cache"
        subdir.mkdir()
        (subdir / "data_0").write_bytes(b"cache" * 50)
        # Local State (encryption_key reference)
        (user_data / "Local State").write_text(
            '{"os_crypt": {"encrypted_key": "dGVzdGtleQ=="}}',
            encoding="utf-8",
        )
        return user_data, profile

    def test_copies_profile_to_default_subdir(self, tmp_path):
        """副本内层目录固定叫 Default，让 Playwright user_data_dir=target 能找到。"""
        user_data, _ = self._make_source(tmp_path)
        target = tmp_path / "copy_dest"
        result = chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert result["ok"] is True if "ok" in result else True  # dict has keys
        assert (target / "Default").is_dir()
        assert (target / "Default" / "Cookies").is_file()
        assert (target / "Default" / "History").is_file()
        # Cache dir is excluded by the ignore callback (tested separately)
        assert not (target / "Default" / "Cache").exists()

    def test_disk_full_surfaces_clear_error_not_chrome_running(self, tmp_path, monkeypatch):
        """R8：复制时磁盘满（ENOSPC）应报明确「磁盘空间不足」，而不是被当成
        「文件被锁 / Chrome 开着」吞掉（否则每个文件都 ENOSPC→全 skipped→误报关 Chrome）。"""
        import errno as _errno
        user_data, _ = self._make_source(tmp_path)
        target = tmp_path / "copy_dest"

        def _enospc(src, dst, **kw):
            raise OSError(_errno.ENOSPC, "No space left on device")
        monkeypatch.setattr(chrome_detect.shutil, "copy2", _enospc)

        with pytest.raises(OSError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="Default",
                target_path=str(target),
            )
        assert "磁盘空间不足" in str(exc.value)

    def test_copies_local_state(self, tmp_path):
        """Local State 必须被复制到副本根目录。"""
        user_data, _ = self._make_source(tmp_path)
        target = tmp_path / "copy_dest"
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert (target / "Local State").is_file()
        text = (target / "Local State").read_text(encoding="utf-8")
        assert "encrypted_key" in text

    def test_returns_metadata(self, tmp_path):
        """返回 imported_at + size_mb + elapsed_s。"""
        user_data, _ = self._make_source(tmp_path)
        target = tmp_path / "copy_dest"
        meta = chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert "imported_at" in meta
        assert "size_mb" in meta
        assert "elapsed_s" in meta
        assert isinstance(meta["size_mb"], float)
        assert meta["size_mb"] >= 0  # may round to 0.0 for tiny test files
        assert "T" in meta["imported_at"]  # ISO8601 timestamp has 'T'

    def test_clears_old_copy_before_reimport(self, tmp_path):
        """重新导入时先清旧副本，不留残留文件。"""
        user_data, _ = self._make_source(tmp_path)
        target = tmp_path / "copy_dest"
        # First import
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        # Plant a stale file in the copy
        stale = target / "Default" / "stale_file.db"
        stale.write_bytes(b"stale")
        assert stale.is_file()
        # Second import should wipe the target first
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert not stale.is_file(), "stale file should have been cleared on re-import"

    def test_raises_file_not_found_when_source_missing(self, tmp_path):
        """source profile 不存在 → FileNotFoundError（不是静默失败）。"""
        import pytest
        user_data = tmp_path / "User Data"
        user_data.mkdir()
        # No profile dir created
        with pytest.raises(FileNotFoundError):
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="NonExistent",
                target_path=str(tmp_path / "dest"),
            )

    def test_missing_profile_error_lists_available_profiles(self, tmp_path):
        """要复制的 profile 不存在、但目录里有别的 profile → 报错里列出可选项。

        回归 bug：同事的 Chrome 没有 Default（只有 Profile 1），前端写死复制
        "Default" 撞英文 "source profile not found: ...\\Default"，用户完全
        不知道该怎么办。错误必须说明「有哪些可选」。
        """
        user_data = tmp_path / "User Data"
        (user_data / "Profile 1").mkdir(parents=True)
        (user_data / "Profile 2").mkdir()
        with pytest.raises(FileNotFoundError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="Default",
                target_path=str(tmp_path / "dest"),
            )
        msg = str(exc.value)
        assert "Default" in msg
        assert "Profile 1" in msg and "Profile 2" in msg

    def test_missing_profile_error_when_dir_has_no_profiles(self, tmp_path):
        """User Data 存在但一个 profile 都没有（Chrome 装了没启动过）→
        提示「先启动一次 Chrome」而不是干巴巴的 not found。"""
        user_data = tmp_path / "User Data"
        (user_data / "Crashpad").mkdir(parents=True)  # 非 profile 目录
        with pytest.raises(FileNotFoundError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="Default",
                target_path=str(tmp_path / "dest"),
            )
        assert "启动" in str(exc.value)

    def test_refuses_to_copy_when_target_is_inside_source(self, tmp_path):
        """副本目录 = 源目录（或互相嵌套）时必须先拦下 —— copy_profile_to 上来就
        rmtree(target)，一旦源就是副本本身，用户 14GB 的副本和副本里的百度登录态
        会被直接抹掉。手填数据目录后这条路径变得可达（副本内层目录也叫 Default，
        连 profile 检查都能通过）。"""
        copy_dir = tmp_path / "baidu_chrome_profile_copy"
        (copy_dir / "Default").mkdir(parents=True)
        (copy_dir / "Default" / "Cookies").write_bytes(b"login")
        with pytest.raises(ValueError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(copy_dir),
                source_profile_name="Default",
                target_path=str(copy_dir),
            )
        assert "副本" in str(exc.value)
        # 关键：什么都没删
        assert (copy_dir / "Default" / "Cookies").is_file()

    def test_refuses_when_source_is_inside_target(self, tmp_path):
        target = tmp_path / "copy"
        source = target / "nested" / "User Data"
        (source / "Default").mkdir(parents=True)
        (source / "Default" / "Cookies").write_bytes(b"login")
        with pytest.raises(ValueError):
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(source),
                source_profile_name="Default",
                target_path=str(target),
            )
        assert (source / "Default" / "Cookies").is_file()

    def test_rejects_profile_name_that_is_not_a_chrome_profile(self, tmp_path):
        """profile 名只接受 Default / Profile N —— 顺带挡住 "../x" 被当 profile 复制。"""
        user_data = tmp_path / "User Data"
        (user_data / "Default").mkdir(parents=True)
        (tmp_path / "secret").mkdir()
        (tmp_path / "secret" / "f.txt").write_text("x")
        with pytest.raises(FileNotFoundError):
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="../secret",
                target_path=str(tmp_path / "dest"),
            )
        assert not (tmp_path / "dest").exists()

    def test_rejects_empty_profile_name(self, tmp_path):
        """空名字下 Path(dir) / "" == Path(dir)，会把整个 User Data 当 profile 复制。"""
        user_data = tmp_path / "User Data"
        (user_data / "Default").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="",
                target_path=str(tmp_path / "dest"),
            )

    def test_hints_when_user_pointed_one_level_too_deep(self, tmp_path):
        """用户把报错里的 ...\\User Data\\Default 原样粘回来（多填一层）→
        提示"多填了一层"，而不是"请先启动一次 Chrome"（他刚启动过）。"""
        deep = tmp_path / "User Data" / "Default"
        deep.mkdir(parents=True)
        (deep / "Preferences").write_text("{}", encoding="utf-8")
        with pytest.raises(FileNotFoundError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(deep),
                source_profile_name="Default",
                target_path=str(tmp_path / "dest"),
            )
        assert "多填了一层" in str(exc.value)

    def test_missing_user_data_dir_error_is_distinct(self, tmp_path):
        """User Data 目录本身不存在 → 提示手动填目录，跟「没有 profile」区分开。"""
        missing = tmp_path / "nope" / "User Data"
        with pytest.raises(FileNotFoundError) as exc:
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(missing),
                source_profile_name="Default",
                target_path=str(tmp_path / "dest"),
            )
        assert "不存在" in str(exc.value)

    def test_works_without_local_state(self, tmp_path):
        """没有 Local State 文件时不抛，只复制 profile。"""
        user_data = tmp_path / "User Data"
        user_data.mkdir()
        profile = user_data / "Default"
        profile.mkdir()
        (profile / "Cookies").write_bytes(b"data")
        # No "Local State" file
        target = tmp_path / "dest"
        meta = chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert (target / "Default" / "Cookies").is_file()
        assert not (target / "Local State").is_file()
        assert "imported_at" in meta

    def test_non_default_profile_name_maps_to_default(self, tmp_path):
        """源 Profile 1 → 副本内层目录叫 Default（不是 Profile 1）。"""
        user_data, _ = self._make_source(tmp_path, profile_name="Profile 1")
        target = tmp_path / "dest"
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(user_data),
            source_profile_name="Profile 1",
            target_path=str(target),
        )
        # target inner dir is always Default
        assert (target / "Default").is_dir()
        assert (target / "Default" / "Cookies").is_file()

    def test_copy_profile_to_skips_cache_dirs(self, tmp_path):
        """复制时跳过 Cache / Code Cache / Service Worker 等无用的临时数据。"""
        src_user_data = tmp_path / "src_user_data"
        src_default = src_user_data / "Default"
        src_default.mkdir(parents=True)
        # 关键文件（保留）
        (src_default / "Cookies").write_text("cookies-data")
        (src_default / "Login Data").write_text("login-data")
        (src_default / "Preferences").write_text('{"profile":{}}')
        (src_user_data / "Local State").write_text('{"os_crypt":{}}')
        # cache 子目录（应该被跳过）
        (src_default / "Cache").mkdir()
        (src_default / "Cache" / "data_0").write_text("cache-blob-1MB")
        (src_default / "Code Cache").mkdir()
        (src_default / "Code Cache" / "js").mkdir()
        (src_default / "Code Cache" / "js" / "f.bin").write_text("js-cache")
        (src_default / "Service Worker").mkdir()
        (src_default / "Service Worker" / "CacheStorage").mkdir()
        (src_default / "GPUCache").mkdir()

        target = tmp_path / "target"
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(src_user_data),
            source_profile_name="Default",
            target_path=str(target),
        )

        # 关键文件复制了
        assert (target / "Default" / "Cookies").exists()
        assert (target / "Default" / "Login Data").exists()
        assert (target / "Default" / "Preferences").exists()
        assert (target / "Local State").exists()
        # cache 目录没复制
        assert not (target / "Default" / "Cache").exists()
        assert not (target / "Default" / "Code Cache").exists()
        assert not (target / "Default" / "Service Worker").exists()
        assert not (target / "Default" / "GPUCache").exists()

    def test_copy_profile_to_skips_cachestorage_and_shared_dictionary(self, tmp_path):
        """WebStorage 下的 CacheStorage 和 Shared Dictionary 也跳过（纯缓存），
        同 bucket 的非缓存数据（leveldb）保留。"""
        src_user_data = tmp_path / "src_user_data"
        src_default = src_user_data / "Default"
        src_default.mkdir(parents=True)
        (src_default / "Cookies").write_text("cookies-data")
        (src_user_data / "Local State").write_text('{"os_crypt":{}}')
        # WebStorage/<bucket>/CacheStorage —— 缓存，跳过
        cs = src_default / "WebStorage" / "1" / "CacheStorage"
        cs.mkdir(parents=True)
        (cs / "blob").write_text("cache-blob")
        # WebStorage/<bucket>/leveldb —— 非缓存，保留
        other = src_default / "WebStorage" / "1" / "leveldb"
        other.mkdir(parents=True)
        (other / "000001.log").write_text("real-data")
        # Shared Dictionary —— 缓存，跳过
        sd = src_default / "Shared Dictionary"
        sd.mkdir()
        (sd / "db").write_text("dict-cache")

        target = tmp_path / "target"
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(src_user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert (target / "Default" / "Cookies").exists()
        # CacheStorage 任意层级都不复制
        assert not (target / "Default" / "WebStorage" / "1" / "CacheStorage").exists()
        # 同 bucket 的非缓存数据保留
        assert (target / "Default" / "WebStorage" / "1" / "leveldb" / "000001.log").exists()
        # Shared Dictionary 不复制
        assert not (target / "Default" / "Shared Dictionary").exists()

    def test_tolerates_locked_files_instead_of_failing(self, tmp_path, monkeypatch):
        """用户日常 Chrome 开着时 Cookies / LOCK 被独占锁 —— 复制不再整体失败。

        回归 bug：原来裸 shutil.copytree 一遇 [Errno 13] 就在最后抛 shutil.Error，
        整次导入判失败（哪怕 99% 文件已复制好）。现在：LOCK 按名跳过、被锁的
        Cookies 吞错并记入 skipped_locked + 返回 warning，复制整体成功。
        """
        import shutil

        src_user_data = tmp_path / "src_user_data"
        src_default = src_user_data / "Default"
        src_default.mkdir(parents=True)
        (src_default / "Cookies").write_bytes(b"cookie-db")     # 模拟被锁
        (src_default / "Preferences").write_text('{"profile":{}}')  # 正常复制
        (src_user_data / "Local State").write_text('{"os_crypt":{}}')
        # 嵌套 leveldb LOCK —— 运行时锁哨兵，应被 ignore 跳过（根本不尝试复制）
        lvldb = src_default / "Local Storage" / "leveldb"
        lvldb.mkdir(parents=True)
        (lvldb / "LOCK").write_bytes(b"")
        (lvldb / "000003.log").write_text("real-data")

        # 模拟 Chrome 把 Cookies 锁住 —— 复制它必 PermissionError，其它文件正常。
        real_copy2 = shutil.copy2

        def fake_copy2(src, dst, *a, **k):
            if os.path.basename(str(src)) in ("Cookies", "Cookies-journal"):
                raise PermissionError(13, "Permission denied")
            return real_copy2(src, dst, *a, **k)

        monkeypatch.setattr(shutil, "copy2", fake_copy2)

        target = tmp_path / "target"
        # 关键：不再抛异常
        meta = chrome_detect.copy_profile_to(
            source_user_data_dir=str(src_user_data),
            source_profile_name="Default",
            target_path=str(target),
        )

        # 没被锁的文件照常复制
        assert (target / "Default" / "Preferences").exists()
        assert (target / "Local State").exists()
        assert (target / "Default" / "Local Storage" / "leveldb" / "000003.log").exists()
        # LOCK 按名跳过，不进副本（残留锁会让副本 Chromium 误判被占）
        assert not (target / "Default" / "Local Storage" / "leveldb" / "LOCK").exists()
        # 被锁的 Cookies 跳过 + 计入 skipped_locked + 给 warning
        assert not (target / "Default" / "Cookies").exists()
        assert "Cookies" in meta["skipped_locked"]
        assert meta["warning"] is not None
        assert "登录" in meta["warning"]

    def test_no_warning_when_nothing_locked(self, tmp_path):
        """正常路径（没有文件被锁）→ warning 为 None、skipped_locked 为空。"""
        src_user_data = tmp_path / "src_user_data"
        src_default = src_user_data / "Default"
        src_default.mkdir(parents=True)
        (src_default / "Cookies").write_bytes(b"cookie-db")
        (src_user_data / "Local State").write_text('{"os_crypt":{}}')

        meta = chrome_detect.copy_profile_to(
            source_user_data_dir=str(src_user_data),
            source_profile_name="Default",
            target_path=str(tmp_path / "target"),
        )
        assert meta["warning"] is None
        assert meta["skipped_locked"] == []


# ── prune_profile_caches ──────────────────────────────────────────
class TestPruneProfileCaches:
    def _make_copy(self, tmp_path):
        """造一个带缓存 + 登录态的假副本。"""
        copy = tmp_path / "baidu_chrome_profile_copy"
        default = copy / "Default"
        default.mkdir(parents=True)
        # 缓存（应删）
        sw = default / "Service Worker" / "CacheStorage"
        sw.mkdir(parents=True)
        (sw / "blob").write_bytes(b"x" * 4096)
        (default / "Cache").mkdir()
        (default / "Cache" / "data_0").write_bytes(b"y" * 4096)
        ws_cs = default / "WebStorage" / "1" / "CacheStorage"
        ws_cs.mkdir(parents=True)
        (ws_cs / "blob").write_bytes(b"z" * 4096)
        (default / "Shared Dictionary").mkdir()
        (default / "Shared Dictionary" / "db").write_bytes(b"w" * 4096)
        # 登录态 / 用户数据（应留）
        (default / "Network").mkdir()
        (default / "Network" / "Cookies").write_bytes(b"login-cookies")
        (default / "IndexedDB").mkdir()
        (default / "IndexedDB" / "data").write_bytes(b"idb")
        (default / "Local Storage").mkdir()
        (default / "Local Storage" / "leveldb").write_bytes(b"ls")
        (copy / "Local State").write_text('{"os_crypt":{}}')
        return copy, default

    def test_removes_caches_keeps_login_state(self, tmp_path):
        copy, default = self._make_copy(tmp_path)
        meta = chrome_detect.prune_profile_caches(str(copy))
        # 缓存删了（含任意层级 CacheStorage）
        assert not (default / "Service Worker").exists()
        assert not (default / "Cache").exists()
        assert not (default / "WebStorage" / "1" / "CacheStorage").exists()
        assert not (default / "Shared Dictionary").exists()
        # 登录态 / 用户数据留着
        assert (default / "Network" / "Cookies").exists()
        assert (default / "IndexedDB" / "data").exists()
        assert (default / "Local Storage" / "leveldb").exists()
        assert (copy / "Local State").exists()
        # 返回释放量元数据
        assert meta["freed_mb"] >= 0
        assert "elapsed_s" in meta

    def test_nonexistent_path_is_noop(self, tmp_path):
        meta = chrome_detect.prune_profile_caches(str(tmp_path / "nope"))
        assert meta == {"freed_mb": 0.0, "elapsed_s": 0.0}

    def test_does_not_raise_when_removal_fails(self, tmp_path, monkeypatch):
        """rmtree 抛错（模拟文件锁）时整体不冒泡。"""
        copy, _ = self._make_copy(tmp_path)

        def boom(*a, **k):
            raise OSError("locked")

        monkeypatch.setattr(chrome_detect.shutil, "rmtree", boom)
        meta = chrome_detect.prune_profile_caches(str(copy))  # 不应抛
        assert "freed_mb" in meta and "elapsed_s" in meta
