"""Shared pytest fixtures for sidecar tests.

Two responsibilities:

1. Reset module-level singletons (config_service path, vault_service cache,
   storage db) between tests so test order can't leak state.
2. Build an authenticated TestClient that auto-attaches the bearer token
   so individual tests don't have to repeat the boilerplate.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage as monitor_storage
from csm_sidecar import auth
from csm_sidecar.main import app
from csm_sidecar.services import config_service, factcheck_service, vault_service


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    """Per-test settings.json path. Resets the config_service singleton."""
    p = tmp_path / "settings.json"
    config_service.init(p)
    yield p
    # Reset to defaults so the next test re-init's cleanly.
    config_service.init(None)


@pytest.fixture
def vault_cache_reset() -> Iterator[None]:
    yield
    vault_service.invalidate()


@pytest.fixture
def monitor_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test sqlite DB. Resets storage module globals (re-init guard)."""
    db_file = tmp_path / "monitor.db"
    monkeypatch.setattr(monitor_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(monitor_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(monitor_storage, "_local", threading.local(), raising=True)
    monitor_storage.init_db(db_file)
    return db_file


@pytest.fixture
def xhs_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test 独立 xhs.db。重置 storage 模块全局（解除 re-init 守卫）。"""
    from csm_core.xhs import storage as xhs_storage
    db_file = tmp_path / "xhs.db"
    monkeypatch.setattr(xhs_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(xhs_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(xhs_storage, "_local", threading.local(), raising=True)
    xhs_storage.init_db(db_file)
    return db_file


@pytest.fixture
def client(settings_path: Path, vault_cache_reset) -> Iterator[TestClient]:
    """Authenticated TestClient. Token is minted on app startup (lifespan).

    The lifespan handler runs on first ``with TestClient(app)`` entry, so
    we need to enter the context to get the token, then attach it to every
    subsequent request.
    """
    factcheck_service.reset_for_test()
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {auth.get_token()}"
        yield c
    factcheck_service.reset_for_test()
