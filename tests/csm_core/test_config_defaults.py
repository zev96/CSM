"""default_*_dir helpers — pure path computation, no I/O."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from csm_core import config as core_config


def test_default_templates_dir_under_config_dir():
    assert core_config.default_templates_dir() == core_config.default_config_dir() / "Templates"


def test_default_skills_dir_under_config_dir():
    assert core_config.default_skills_dir() == core_config.default_config_dir() / "Skills"


def test_default_history_dir_under_config_dir():
    assert core_config.default_history_dir() == core_config.default_config_dir() / "History"


def test_helpers_return_path_objects():
    assert isinstance(core_config.default_templates_dir(), Path)
    assert isinstance(core_config.default_skills_dir(), Path)
    assert isinstance(core_config.default_history_dir(), Path)


@pytest.mark.skipif(sys.platform != "win32", reason="windows path layout only")
def test_default_config_dir_is_outside_install_dir_on_windows(monkeypatch, tmp_path):
    """The CSM data dir MUST NOT be a subdir of the NSIS install dir.

    Pre-v0.4.5 we had data at ``%LOCALAPPDATA%/CSM/CSM`` and the NSIS
    install at ``%LOCALAPPDATA%/CSM`` — hot-update would wipe user data
    by renaming the install dir. v0.4.5 moves data to a sibling so
    they're independent.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = core_config.default_config_dir()
    install = tmp_path / "CSM"
    # Data must not be inside install dir, and they must not collide.
    assert install not in data.parents
    assert data != install


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only legacy path")
def test_legacy_config_dir_win_points_at_old_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert core_config.legacy_config_dir_win() == tmp_path / "CSM" / "CSM"


@pytest.mark.skipif(sys.platform != "win32", reason="migration runs on windows only")
def test_migrate_legacy_config_dir_copies_old_to_new(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    old = core_config.legacy_config_dir_win()
    old.mkdir(parents=True)
    (old / "settings.json").write_text('{"foo": "bar"}', encoding="utf-8")
    (old / "monitor.db").write_bytes(b"\x00\x01fake-sqlite")

    new = core_config.default_config_dir()
    assert not new.exists()

    moved = core_config.migrate_legacy_config_dir()
    assert moved is True
    assert (new / "settings.json").read_text(encoding="utf-8") == '{"foo": "bar"}'
    assert (new / "monitor.db").read_bytes() == b"\x00\x01fake-sqlite"
    # Old retained as backup — we don't delete on migration
    assert (old / "settings.json").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="migration runs on windows only")
def test_migrate_legacy_config_dir_noop_when_new_populated(monkeypatch, tmp_path):
    """Don't overwrite an already-populated new dir."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    old = core_config.legacy_config_dir_win()
    old.mkdir(parents=True)
    (old / "settings.json").write_text('{"version": "old"}', encoding="utf-8")

    new = core_config.default_config_dir()
    new.mkdir(parents=True)
    (new / "settings.json").write_text('{"version": "new"}', encoding="utf-8")

    moved = core_config.migrate_legacy_config_dir()
    assert moved is False
    # New left untouched
    assert (new / "settings.json").read_text(encoding="utf-8") == '{"version": "new"}'


@pytest.mark.skipif(sys.platform != "win32", reason="migration runs on windows only")
def test_migrate_legacy_config_dir_noop_when_no_old(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    moved = core_config.migrate_legacy_config_dir()
    assert moved is False
