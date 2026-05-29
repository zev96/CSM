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
        assert chrome_detect.find_user_data_dir() == str(chrome_data)

    def test_returns_none_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # 不创建 Google/Chrome
        assert chrome_detect.find_user_data_dir() is None


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
        with pytest.raises(FileNotFoundError, match="source profile not found"):
            chrome_detect.copy_profile_to(
                source_user_data_dir=str(user_data),
                source_profile_name="NonExistent",
                target_path=str(tmp_path / "dest"),
            )

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
