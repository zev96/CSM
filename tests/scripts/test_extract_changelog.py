"""scripts/extract_changelog.py — extract one version's section from CHANGELOG.md."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "extract_changelog.py"


def _run(version: str, changelog: Path):
    # encoding="utf-8" — the script writes UTF-8 bytes to stdout to avoid
    # platform codec issues (Windows defaults to cp1252/gbk).
    return subprocess.run(
        [sys.executable, str(SCRIPT), version, str(changelog)],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_extract_extracts_named_section(tmp_path: Path):
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("""# Changelog

## [Unreleased]

### Added
- 未发布的内容

## [0.2.0] - 2026-05-07

### Added
- 系统托盘
- 内容查重

### Fixed
- 修复 XYZ

## [0.1.0] - 2026-04-15

### Added
- 初版
""", encoding="utf-8")
    result = _run("0.2.0", cl)
    assert result.returncode == 0
    assert "系统托盘" in result.stdout
    assert "内容查重" in result.stdout
    assert "未发布的内容" not in result.stdout
    assert "初版" not in result.stdout


def test_extract_strips_section_header(tmp_path: Path):
    """The extracted text should be the body, not the '## [0.2.0] - YYYY...' header."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("""## [0.2.0] - 2026-05-07

### Added
- A
- B

## [0.1.0] - 2026-01-01

- old
""", encoding="utf-8")
    result = _run("0.2.0", cl)
    assert result.returncode == 0
    assert "## [0.2.0]" not in result.stdout
    assert "- A" in result.stdout


def test_extract_missing_version_fails(tmp_path: Path):
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("## [0.1.0] - 2026-01-01\n\n- only\n", encoding="utf-8")
    result = _run("9.9.9", cl)
    assert result.returncode != 0
