"""Tests for ensure_default_dirs() — first-run directory bootstrap."""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_sidecar.services import config_service, startup_dirs


@pytest.fixture
def cfg_path(tmp_path: Path):
    """Per-test settings.json path."""
    p = tmp_path / "settings.json"
    config_service.init(p)
    yield p
    config_service.init(None)


def test_fills_empty_fields_with_defaults(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: tmp_path / "_no_resources_")

    startup_dirs.ensure_default_dirs()

    cfg = config_service.load()
    assert cfg.default_template == str(user_dir / "Templates")
    assert cfg.skill_dir == str(user_dir / "Skills")
    assert cfg.dedup_history_dir == str(user_dir / "History")
    assert (user_dir / "Templates").is_dir()
    assert (user_dir / "Skills").is_dir()
    assert (user_dir / "History").is_dir()


def test_does_not_overwrite_user_chosen_paths(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: tmp_path / "_no_resources_")

    # Pre-populate user's own paths
    my_templates = tmp_path / "elsewhere" / "T"
    config_service.patch({
        "default_template": str(my_templates),
        "skill_dir": "",
        "dedup_history_dir": "",
    })

    startup_dirs.ensure_default_dirs()

    cfg = config_service.load()
    # User's choice preserved (and mkdir'd):
    assert cfg.default_template == str(my_templates)
    assert my_templates.is_dir()
    # Empty fields filled:
    assert cfg.skill_dir == str(user_dir / "Skills")
    assert cfg.dedup_history_dir == str(user_dir / "History")


def test_seeds_templates_when_user_dir_is_empty(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    resource_dir = tmp_path / "resources"
    (resource_dir / "templates").mkdir(parents=True)
    (resource_dir / "templates" / "demo.json").write_text('{"v": 1}', encoding="utf-8")
    (resource_dir / "examples" / "skills").mkdir(parents=True)
    (resource_dir / "examples" / "skills" / "demo.md").write_text("# demo", encoding="utf-8")

    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: resource_dir)

    startup_dirs.ensure_default_dirs()

    assert (user_dir / "Templates" / "demo.json").is_file()
    assert (user_dir / "Skills" / "demo.md").is_file()


def test_does_not_re_seed_when_target_already_has_files(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    (user_dir / "Templates").mkdir(parents=True)
    (user_dir / "Templates" / "user_made.json").write_text("user", encoding="utf-8")

    resource_dir = tmp_path / "resources"
    (resource_dir / "templates").mkdir(parents=True)
    (resource_dir / "templates" / "demo.json").write_text('{"v": 1}', encoding="utf-8")

    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: resource_dir)

    startup_dirs.ensure_default_dirs()

    # Seed must NOT copy demo.json because Templates dir is non-empty.
    assert not (user_dir / "Templates" / "demo.json").exists()
    assert (user_dir / "Templates" / "user_made.json").is_file()
