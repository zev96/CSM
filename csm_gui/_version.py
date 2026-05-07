"""Single source of truth for CSM's version string.

Bumped by ``scripts/release.py`` on every release. CI's
``scripts/release_check.py`` enforces that the git tag matches.
"""
__version__ = "0.1.0"
