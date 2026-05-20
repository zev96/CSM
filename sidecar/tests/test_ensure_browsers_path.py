"""Tests for ``patchright_pool.ensure_browsers_path`` lookup priority.

Three-tier priority added in v0.5.3 to fix the "release installer ships
without Chromium" bug — see CHANGELOG v0.5.3:

    1. ``PLAYWRIGHT_BROWSERS_PATH`` env var (user/dev override)
    2. Bundled ``<sidecar-exe-dir>/binaries/ms-playwright/`` (release)
    3. User-wide cache ``%LOCALAPPDATA%\\ms-playwright`` etc. (dev/legacy)

Each test isolates one priority layer by mocking the others away.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from csm_core.browser_infra import patchright_pool


@pytest.fixture(autouse=True)
def _reset_log_flag():
    """``_browsers_path_logged`` is a module-level flag that suppresses
    duplicate log lines; reset between tests so each one exercises the
    fresh-call code path."""
    patchright_pool._browsers_path_logged = False
    yield
    patchright_pool._browsers_path_logged = False


def test_env_var_wins(monkeypatch, tmp_path):
    """Priority 1: explicit env var short-circuits everything."""
    explicit = tmp_path / "user-supplied-ms-playwright"
    explicit.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(explicit))

    result = patchright_pool.ensure_browsers_path()

    assert result == str(explicit)


def test_bundled_path_used_when_present(monkeypatch, tmp_path):
    """Priority 2: bundled Chromium next to sidecar exe is preferred over
    the user-wide cache (release builds — Tauri resources lays it there)."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    fake_install = tmp_path / "install_dir"
    fake_install.mkdir()
    fake_sidecar = fake_install / "csm-sidecar.exe"
    fake_sidecar.write_bytes(b"")  # presence is enough; resolve() needs a real path
    bundled_ms = fake_install / "binaries" / "ms-playwright"
    bundled_ms.mkdir(parents=True)

    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    result = patchright_pool.ensure_browsers_path()

    assert result == str(bundled_ms.resolve())


def test_bundled_path_set_in_environ(monkeypatch, tmp_path):
    """The function sets ``PLAYWRIGHT_BROWSERS_PATH`` in ``os.environ`` so
    that the Node driver subprocess inherits it. Without this, even
    returning the path doesn't help: patchright's driver reads the env
    var, not our return value."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    fake_install = tmp_path / "install_dir"
    fake_install.mkdir()
    fake_sidecar = fake_install / "csm-sidecar.exe"
    fake_sidecar.write_bytes(b"")
    bundled_ms = fake_install / "binaries" / "ms-playwright"
    bundled_ms.mkdir(parents=True)

    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    patchright_pool.ensure_browsers_path()

    assert __import__("os").environ.get("PLAYWRIGHT_BROWSERS_PATH") == str(bundled_ms.resolve())


def test_user_cache_fallback_when_no_bundle(monkeypatch, tmp_path):
    """Priority 3: when no env var and no bundled dir, fall back to the
    user-wide cache that ``patchright install chromium`` populates."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    # Sidecar exe somewhere with no neighbour ms-playwright dir.
    fake_install = tmp_path / "install_dir"
    fake_install.mkdir()
    fake_sidecar = fake_install / "csm-sidecar.exe"
    fake_sidecar.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    # User-wide cache exists (Windows path — Win-only since CSM is Windows-only).
    user_cache = tmp_path / "LocalAppData" / "ms-playwright"
    user_cache.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    result = patchright_pool.ensure_browsers_path()

    assert result == str(user_cache)


def test_returns_none_when_nothing_exists(monkeypatch, tmp_path):
    """All three layers miss → return ``None`` and log a warning. Caller
    will then try to launch and patchright will produce the canonical
    "Executable doesn't exist" error, which the route maps to a 503 with
    a setup hint."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    fake_install = tmp_path / "install_dir"
    fake_install.mkdir()
    fake_sidecar = fake_install / "csm-sidecar.exe"
    fake_sidecar.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData_does_not_exist"))

    result = patchright_pool.ensure_browsers_path()

    assert result is None


def test_bundled_takes_priority_over_user_cache(monkeypatch, tmp_path):
    """When both bundled AND user-wide exist, bundled wins. This matters
    because dev machines often have a stale ``%LOCALAPPDATA%/ms-playwright``
    from a different patchright version; the release-bundled one is the
    pinned-tested version and should take precedence."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    fake_install = tmp_path / "install_dir"
    fake_install.mkdir()
    fake_sidecar = fake_install / "csm-sidecar.exe"
    fake_sidecar.write_bytes(b"")
    bundled_ms = fake_install / "binaries" / "ms-playwright"
    bundled_ms.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    user_cache = tmp_path / "LocalAppData" / "ms-playwright"
    user_cache.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    result = patchright_pool.ensure_browsers_path()

    assert result == str(bundled_ms.resolve())
