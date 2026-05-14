"""scripts/release_check.py — verify git tag matches tauri.conf.json version."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_check.py"
TAURI_CONF = ROOT / "frontend" / "src-tauri" / "tauri.conf.json"


def _run(tag: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag],
        capture_output=True, text=True, cwd=ROOT,
    )


def _current_version() -> str:
    return json.loads(TAURI_CONF.read_text(encoding="utf-8"))["version"]


def test_release_check_passes_on_match():
    """When tag (vX.Y.Z) matches tauri.conf.json::version, exit 0."""
    result = _run(f"v{_current_version()}")
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
    result = _run(_current_version())  # no v-prefix
    assert result.returncode == 0, f"stderr: {result.stderr}"
