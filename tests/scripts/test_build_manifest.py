"""scripts/build_manifest.py — build a manifest.json from a zip and version."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_manifest.py"


def _make_zip(tmp_path: Path) -> Path:
    z = tmp_path / "CSM-v0.2.0.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CSM/dummy.txt", "hi")
    return z


def test_build_manifest_writes_json(tmp_path: Path):
    z = _make_zip(tmp_path)
    out = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.2.0", "--zip", str(z),
         "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == "0.2.0"
    assert data["asset_size"] > 0
    assert len(data["sha256"]) == 64  # 64 hex chars
    expected = hashlib.sha256(z.read_bytes()).hexdigest()
    assert data["sha256"] == expected


def test_build_manifest_includes_released_at(tmp_path: Path):
    z = _make_zip(tmp_path)
    out = tmp_path / "manifest.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.2.0", "--zip", str(z),
         "--out", str(out)],
        check=True, cwd=ROOT,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "released_at" in data
    assert "T" in data["released_at"]


def test_build_manifest_includes_min_compatible(tmp_path: Path):
    """--min-compatible flag is plumbed into manifest."""
    z = _make_zip(tmp_path)
    out = tmp_path / "manifest.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.2.0", "--zip", str(z),
         "--out", str(out), "--min-compatible", "0.1.0"],
        check=True, cwd=ROOT,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["min_compatible_version"] == "0.1.0"
