"""chrome_preflight.py 单元测试 —— mock psutil 模拟 Chrome 进程状态。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from csm_core.monitor.drivers import chrome_preflight


class TestIsChromeRunning:
    def test_returns_true_when_chrome_exe_running(self, monkeypatch):
        fake_proc = MagicMock()
        fake_proc.info = {"name": "chrome.exe"}
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [fake_proc])
        assert chrome_preflight.is_chrome_running() is True

    def test_returns_false_when_only_other_processes(self, monkeypatch):
        fake_proc = MagicMock()
        fake_proc.info = {"name": "firefox.exe"}
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [fake_proc])
        assert chrome_preflight.is_chrome_running() is False

    def test_case_insensitive_name_match(self, monkeypatch):
        fake_proc = MagicMock()
        fake_proc.info = {"name": "Chrome.exe"}  # 大写
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [fake_proc])
        assert chrome_preflight.is_chrome_running() is True

    def test_skips_processes_raising_access_denied(self, monkeypatch):
        import psutil
        bad_proc = MagicMock()
        type(bad_proc).info = property(lambda self: (_ for _ in ()).throw(psutil.AccessDenied()))
        good_proc = MagicMock()
        good_proc.info = {"name": "chrome.exe"}
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [bad_proc, good_proc])
        assert chrome_preflight.is_chrome_running() is True


class TestWaitForChromeClosed:
    def test_returns_immediately_when_chrome_not_running(self, monkeypatch):
        monkeypatch.setattr(chrome_preflight, "is_chrome_running", lambda: False)
        notify_calls: list = []
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: notify_calls.append(kw))
        # 不超时 + 不调通知
        chrome_preflight.wait_for_chrome_closed(timeout_s=5, poll_interval_s=0.01)
        assert notify_calls == []  # 没必要发通知

    def test_polls_and_returns_when_chrome_closes_mid_wait(self, monkeypatch):
        """前 2 次 poll 在跑、第 3 次关闭。"""
        state = {"calls": 0}

        def fake_is_running():
            state["calls"] += 1
            return state["calls"] <= 2

        monkeypatch.setattr(chrome_preflight, "is_chrome_running", fake_is_running)
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: None)

        chrome_preflight.wait_for_chrome_closed(timeout_s=5, poll_interval_s=0.01)
        assert state["calls"] >= 3  # 至少 poll 了 3 次

    def test_raises_after_timeout(self, monkeypatch):
        """一直在跑 → 超时 raise。"""
        monkeypatch.setattr(chrome_preflight, "is_chrome_running", lambda: True)
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: None)

        with pytest.raises(chrome_preflight.ChromeStillRunningError) as exc:
            chrome_preflight.wait_for_chrome_closed(timeout_s=0.05, poll_interval_s=0.01)
        assert "超时" in str(exc.value) or "timeout" in str(exc.value).lower()

    def test_emits_notification_on_first_running_detection(self, monkeypatch):
        """第一次检测到在跑 → 发通知，之后不重复发。"""
        state = {"calls": 0}
        def fake_is_running():
            state["calls"] += 1
            return state["calls"] <= 3

        notify_calls: list = []
        monkeypatch.setattr(chrome_preflight, "is_chrome_running", fake_is_running)
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: notify_calls.append(kw))

        chrome_preflight.wait_for_chrome_closed(timeout_s=5, poll_interval_s=0.01)
        assert len(notify_calls) == 1  # 只发一次通知
        assert "关闭 Chrome" in notify_calls[0].get("body", "")
