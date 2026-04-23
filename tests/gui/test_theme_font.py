"""Regression: OPPO Sans is bundled and installed as the app default."""
from __future__ import annotations
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from csm_gui.theme import _FONT_PATH, _install_font, apply_theme


def test_font_file_is_bundled():
    """The OPPO Sans TTF must live under csm_gui/assets/fonts/ so
    ``package-data`` in pyproject.toml picks it up for installs."""
    assert _FONT_PATH.is_file(), (
        f"bundled font missing at {_FONT_PATH} — check pyproject's "
        "[tool.setuptools.package-data] section ships it"
    )


def test_install_font_registers_family(qapp):
    family = _install_font()
    assert family is not None
    # OPPO Sans' family name starts with "OPPO" — we don't hard-code the
    # exact string because different TTF builds report it slightly
    # differently ("OPPO Sans", "OPPOSans", "OPPO Sans 4.0").
    assert "oppo" in family.lower()


def test_apply_theme_sets_application_font(qapp):
    apply_theme()
    fam = qapp.font().family()
    families = qapp.font().families()
    # Either the resolved family or the family stack should mention OPPO.
    combined = " ".join([fam] + list(families)).lower()
    assert "oppo" in combined
