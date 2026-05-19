"""Tests for PATCH /api/config hot-reload behavior.

Verifies that monitor.* changes trigger monitor_lifecycle.reconfigure(),
and that non-monitor changes don't (avoid wasting cycles).

Fixture notes:
- Uses the shared ``client`` fixture from conftest.py, which handles
  auth (Authorization: Bearer) and config_service.init(tmp_path).
- ``settings_path`` (implicit in ``client``) resets config_service after
  each test so there is no cross-test leakage.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from csm_core.config import AppConfig
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
from csm_sidecar.services import monitor_lifecycle


def test_patch_monitor_calls_reconfigure(client: TestClient):
    """PATCH with monitor.* should call monitor_lifecycle.reconfigure."""
    with patch.object(monitor_lifecycle, "reconfigure") as mock_recfg:
        resp = client.patch(
            "/api/config",
            json={"monitor": {"baidu_keyword": {"default_excluded_domains": ["a.com"]}}},
        )
    assert resp.status_code == 200
    assert mock_recfg.call_count == 1
    (call_cfg,) = mock_recfg.call_args.args
    assert isinstance(call_cfg, AppConfig)
    assert "a.com" in call_cfg.monitor.baidu_keyword.default_excluded_domains


def test_patch_non_monitor_skips_reconfigure(client: TestClient, tmp_path):
    """PATCH touching only non-monitor fields should NOT call reconfigure."""
    with patch.object(monitor_lifecycle, "reconfigure") as mock_recfg:
        resp = client.patch("/api/config", json={"vault_root": str(tmp_path)})
    assert resp.status_code == 200
    assert mock_recfg.call_count == 0


def test_patch_default_excluded_domains_visible_to_adapter(client: TestClient):
    """End-to-end: PATCH the domain list, observe BAIDU_ADAPTER updated.

    This is the user-visible fix for Bug 3: edit in SettingsView ->
    adapter's internal state changes WITHOUT a sidecar restart.
    """
    # Force monitor_lifecycle into "loop running" state so reconfigure()
    # doesn't short-circuit on `_loop is None`. reconfigure only checks
    # `_loop is None`, doesn't touch attrs -- any non-None placeholder works.
    fake_loop = object()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        resp = client.patch(
            "/api/config",
            json={"monitor": {"baidu_keyword": {
                "default_excluded_domains": ["bug3-test.example"],
            }}},
        )
        assert resp.status_code == 200
        # Adapter should have picked up the new value
        assert "bug3-test.example" in BAIDU_ADAPTER._default_excluded_domains  # noqa: SLF001
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001 -- reset for other tests
