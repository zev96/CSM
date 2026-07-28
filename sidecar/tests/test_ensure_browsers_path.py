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


def _make_bundle(path: Path) -> Path:
    """造一个**真的**随包 Chromium 目录。

    ⚠ 光 mkdir 一个空的 ``binaries/ms-playwright/`` 是不够的：
    ``ensure_browsers_path`` 要求里面至少有一个 ``chromium*`` 子目录才认。
    这条硬化是后来加的 —— Tauri 把 ``binaries/ms-playwright/`` 声明成
    bundle.resources，每次 dev 启动都会把它镜像进 ``target/debug/binaries/``，
    连空占位一起镜像；空目录能通过 ``.exists()``，于是 patchright 被指进一个
    没有 chromium 的文件夹，还挡死了回落到真正可用的 LOCALAPPDATA 缓存。
    这三条测试写在硬化之前，一直建空目录、一直按旧行为断言，于是长期是红的。
    """
    path.mkdir(parents=True)
    (path / "chromium-1148").mkdir()
    return path


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """重置模块级状态，并**还原 ``PLAYWRIGHT_BROWSERS_PATH``**。

    ``_browsers_path_logged`` 是抑制重复日志的模块级 flag，逐测重置才能走到
    fresh-call 分支。

    ⚠ env 那半边不能只靠 ``monkeypatch.delenv(..., raising=False)``：key 本就
    不存在时 pytest 的 delitem **什么都不记录**，而被测函数命中优先级 2/3 时会
    **真的写** ``os.environ["PLAYWRIGHT_BROWSERS_PATH"]``（patchright_pool.py
    的 set 语句）—— 这笔写入不是 monkeypatch 做的，teardown 无从回滚，于是一个
    指向 pytest tmp 目录的值泄漏到整个 sidecar 会话。今天不炸只是因为其余用例都
    把 ``ensure_browsers_path`` 打桩成 ``lambda: None``；将来任何一条真调它的
    测试排在本文件之后，会命中优先级 1 的 env 短路，拿到一个早已被 GC 的临时
    路径，症状是「Chromium 找不到」而不是「测试隔离坏了」，根因极难定位。
    """
    import os
    saved = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    patchright_pool._browsers_path_logged = False
    yield
    patchright_pool._browsers_path_logged = False
    if saved is None:
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    else:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = saved


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
    _make_bundle(bundled_ms)

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
    _make_bundle(bundled_ms)

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
    _make_bundle(bundled_ms)
    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    user_cache = tmp_path / "LocalAppData" / "ms-playwright"
    user_cache.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    result = patchright_pool.ensure_browsers_path()

    assert result == str(bundled_ms.resolve())


def test_empty_bundled_dir_is_ignored(monkeypatch, tmp_path):
    """空的 ``binaries/ms-playwright/`` 必须被跳过，回落到用户缓存。

    这正是上面三条测试当年失效的原因，反过来说明它从没被正面测过：Tauri 会
    把空占位镜像进 target/debug，若被采纳，dev 机上 patchright 会被指进一个
    没有 chromium 的目录，且再也回落不到装好的 LOCALAPPDATA 缓存。
    """
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    fake_install = tmp_path / "install_dir"
    fake_install.mkdir()
    fake_sidecar = fake_install / "csm-sidecar.exe"
    fake_sidecar.write_bytes(b"")
    (fake_install / "binaries" / "ms-playwright").mkdir(parents=True)   # 空占位
    monkeypatch.setattr(sys, "executable", str(fake_sidecar))

    user_cache = tmp_path / "LocalAppData" / "ms-playwright"
    user_cache.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert patchright_pool.ensure_browsers_path() == str(user_cache)
