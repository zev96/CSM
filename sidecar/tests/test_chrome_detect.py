"""chrome_detect.py 单元测试 —— mock 注册表 / 文件系统 / Preferences JSON。"""
from __future__ import annotations

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
