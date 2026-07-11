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


def test_reset_baidu_profile_native_mode_targets_copy_dir(client):
    """Native 模式下重置必须删「副本」目录（chrome_profile_copy_path），
    不能删空的自建 profile 目录 —— 否则被风控想重置=静默空操作。"""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle, config_service

    cfg = config_service.load()
    cfg.monitor.baidu_keyword.use_native_chrome = True
    cfg.monitor.baidu_keyword.chrome_profile_copy_path = "D:/x/baidu_chrome_profile_copy"
    config_service.save(cfg)

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: False})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_browser.reset_profile"
        ) as mock_reset:
            resp = client.post("/api/monitor/baidu/reset-profile")
        assert resp.status_code == 204
        mock_reset.assert_called_once()
        args, kwargs = mock_reset.call_args
        passed = kwargs.get("user_data_dir") or (args[0] if args else None)
        assert passed is not None, "native 模式必须显式传副本路径"
        assert "baidu_chrome_profile_copy" in str(passed)
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


def test_copy_has_bduss_detects_cookie(tmp_path):
    """副本 Cookies sqlite 里有 BDUSS 行 → True。"""
    import sqlite3
    from csm_sidecar.routes.monitor import _copy_has_bduss

    netdir = tmp_path / "copy" / "Default" / "Network"
    netdir.mkdir(parents=True)
    conn = sqlite3.connect(netdir / "Cookies")
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value BLOB)")
    conn.execute("INSERT INTO cookies VALUES ('.baidu.com', 'BDUSS', X'00')")
    conn.commit()
    conn.close()
    assert _copy_has_bduss(str(tmp_path / "copy")) is True


def test_copy_has_bduss_absent_when_only_other_cookies(tmp_path):
    """只有 BAIDUID 没有 BDUSS（未登录，只是访问过百度）→ False。"""
    import sqlite3
    from csm_sidecar.routes.monitor import _copy_has_bduss

    netdir = tmp_path / "copy" / "Default" / "Network"
    netdir.mkdir(parents=True)
    conn = sqlite3.connect(netdir / "Cookies")
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value BLOB)")
    conn.execute("INSERT INTO cookies VALUES ('.baidu.com', 'BAIDUID', X'00')")
    conn.commit()
    conn.close()
    assert _copy_has_bduss(str(tmp_path / "copy")) is False


def test_copy_has_bduss_missing_file(tmp_path):
    from csm_sidecar.routes.monitor import _copy_has_bduss

    assert _copy_has_bduss(str(tmp_path / "nonexistent")) is False


def test_launch_login_window_409_when_baidu_task_running(client):
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        resp = client.post("/api/monitor/baidu/launch-login-window")
        assert resp.status_code == 409
        assert "百度任务" in resp.json().get("detail", "")
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_test_native_409_when_baidu_task_running(client):
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        resp = client.post(
            "/api/monitor/baidu/test-native",
            json={"chrome_executable_path": "x", "chrome_profile_copy_path": "y"},
        )
        assert resp.status_code == 409
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_copy_profile_409_when_baidu_task_running(client):
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": "x"},
        )
        assert resp.status_code == 409
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_baidu_login_status_proxies_result(client):
    """GET login-status returns whatever get_login_status produced.
    No 409 gate — read-only operation, safe even with a baidu task running."""
    from unittest.mock import patch

    with patch(
        "csm_core.monitor.drivers.baidu_login.get_login_status",
        return_value={
            "logged_in": True,
            "username": "testuser",
            "expires_at": "2026-07-01T00:00:00+00:00",
        },
    ) as mock_status:
        resp = client.get("/api/monitor/baidu/login-status")

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": True,
        "username": "testuser",
        "expires_at": "2026-07-01T00:00:00+00:00",
    }
    mock_status.assert_called_once()
