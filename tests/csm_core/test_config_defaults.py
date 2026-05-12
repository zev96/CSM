"""default_*_dir helpers — pure path computation, no I/O."""
from __future__ import annotations

from pathlib import Path

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
