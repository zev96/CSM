"""Extract one version's section from CHANGELOG.md (Keep a Changelog format).

Usage:
    python scripts/extract_changelog.py <version> [<changelog-path>]

Outputs the section body (between this version's header and the next
``## [...]`` header) to stdout. The version header line itself is excluded.

CI uses this to populate the GitHub Release body from CHANGELOG.md.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


def extract(text: str, version: str) -> str | None:
    """Return the body of the [version] section, or None if not found."""
    pattern = re.compile(
        rf"^##\s+\[{re.escape(version)}\][^\n]*\n(.*?)(?=^##\s+\[)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    if m:
        return m.group(1).strip("\n")
    # Last section (no ## after it). Match to EOF.
    pattern_last = re.compile(
        rf"^##\s+\[{re.escape(version)}\][^\n]*\n(.*)\Z",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern_last.search(text)
    if m:
        return m.group(1).strip("\n")
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: extract_changelog.py <version> [<changelog-path>]",
              file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    changelog_path = Path(argv[2]) if len(argv) > 2 else Path("CHANGELOG.md")
    if not changelog_path.exists():
        print(f"ERROR: {changelog_path} not found", file=sys.stderr)
        return 1
    text = changelog_path.read_text(encoding="utf-8")
    body = extract(text, version)
    if body is None:
        print(f"ERROR: section [{version}] not found in {changelog_path}",
              file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
