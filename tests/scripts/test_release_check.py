"""scripts/release_check.py — verify git tag matches _version.__version__."""
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_check.py"


def _run(tag: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag],
        capture_output=True, text=True, cwd=ROOT,
    )


def test_release_check_passes_on_match():
    """When tag (vX.Y.Z) matches __version__ (X.Y.Z), exit 0."""
    from csm_gui._version import __version__
    result = _run(f"v{__version__}")
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_release_check_fails_on_mismatch():
    """Tag '99.99.99' doesn't match real version → non-zero exit + diagnostic."""
    result = _run("v99.99.99")
    assert result.returncode != 0
    assert "mismatch" in result.stderr.lower() or "mismatch" in result.stdout.lower()


def test_release_check_fails_on_invalid_semver():
    """Tag without v-prefix or with garbage → fails."""
    result = _run("not-a-tag")
    assert result.returncode != 0


def test_release_check_accepts_v_prefix():
    """Both 'v1.2.3' and '1.2.3' should be accepted as input format."""
    from csm_gui._version import __version__
    result = _run(__version__)  # no v-prefix
    assert result.returncode == 0, f"stderr: {result.stderr}"
