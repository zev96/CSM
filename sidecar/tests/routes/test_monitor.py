"""Tests for /api/monitor/baidu/* routes."""
from __future__ import annotations


def test_reset_baidu_profile_409_when_baidu_task_running(client):
    """If a baidu task is active, reset should refuse with 409."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_browser.reset_profile"
        ) as mock_reset:
            resp = client.post("/api/monitor/baidu/reset-profile")
        assert resp.status_code == 409
        assert "百度任务" in resp.json().get("detail", "")
        mock_reset.assert_not_called()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_reset_baidu_profile_204_when_no_baidu_task(client):
    """No active baidu task → reset_profile is called and returns 204."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: False})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_browser.reset_profile"
        ) as mock_reset:
            resp = client.post("/api/monitor/baidu/reset-profile")
        assert resp.status_code == 204
        mock_reset.assert_called_once()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_baidu_login_409_when_baidu_task_running(client):
    """If a baidu task is active, login should refuse with 409 (would
    fight for the same profile lock)."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_login.open_login_window"
        ) as mock_open:
            resp = client.post("/api/monitor/baidu/login")
        assert resp.status_code == 409
        assert "百度任务" in resp.json().get("detail", "")
        mock_open.assert_not_called()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_baidu_login_success_proxies_result(client):
    """No active baidu task → open_login_window is called, its dict
    result is proxied back to the client."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: False})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_login.open_login_window",
            return_value={"status": "success", "username": "testuser"},
        ) as mock_open:
            resp = client.post("/api/monitor/baidu/login")
        assert resp.status_code == 200
        assert resp.json() == {"status": "success", "username": "testuser"}
        mock_open.assert_called_once()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001
