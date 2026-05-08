"""One-click release: bump version, update CHANGELOG, commit, tag, push.

Usage:
    python scripts/release.py 0.2.0           # actually do it
    python scripts/release.py 0.2.0 --dry-run # show what would happen

Steps:
    1. Verify git tree clean + on main/master branch
    2. Verify new version > current __version__ and is valid semver
    3. Write csm_gui/_version.py
    4. Rewrite CHANGELOG.md: rename [Unreleased] → [X.Y.Z] - YYYY-MM-DD,
       insert fresh empty [Unreleased] above it
    5. git add + commit + tag + push origin main + push origin <tag>
    6. Print URL to GitHub Actions for the user to follow
"""
from __future__ import annotations
import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "csm_gui" / "_version.py"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


def _check_tree_clean() -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if status.strip():
        print("ERROR: working tree is not clean. Commit or stash first.\n"
              + status, file=sys.stderr)
        sys.exit(1)


def _check_branch() -> None:
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if branch not in ("main", "master"):
        print(f"WARN: not on main/master branch (you are on '{branch}'). "
              "Continue? [y/N] ", end="", flush=True)
        if input().strip().lower() != "y":
            sys.exit(1)


def _read_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+(?:-[\w.]+)?)"', text)
    if not m:
        print(f"ERROR: cannot parse __version__ from {VERSION_FILE}",
              file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def _bump_version(new: str) -> None:
    text = VERSION_FILE.read_text(encoding="utf-8")
    text = re.sub(
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new}"',
        text,
    )
    VERSION_FILE.write_text(text, encoding="utf-8")


def _bump_changelog(new: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    today = dt.date.today().isoformat()
    if "## [Unreleased]" not in text:
        print("ERROR: CHANGELOG.md is missing '## [Unreleased]' section",
              file=sys.stderr)
        sys.exit(1)
    text = text.replace(
        "## [Unreleased]",
        f"## [Unreleased]\n\n## [{new}] - {today}",
        1,
    )
    CHANGELOG.write_text(text, encoding="utf-8")


def _semver_gt(new: str, old: str) -> bool:
    """Strict semver comparison ignoring prerelease tags."""
    n = SEMVER_RE.match(new)
    o = SEMVER_RE.match(old)
    if not n or not o:
        return False
    return tuple(int(x) for x in n.group(1, 2, 3)) > \
           tuple(int(x) for x in o.group(1, 2, 3))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="new version, e.g. 0.2.0")
    parser.add_argument("--dry-run", action="store_true",
                        help="don't write files / git anything; just print")
    parser.add_argument("--allow-non-main", action="store_true",
                        help="skip the main/master check")
    args = parser.parse_args(argv[1:])

    new_version = args.version.lstrip("v")
    if not SEMVER_RE.match(new_version):
        print(f"ERROR: '{args.version}' is not valid semver", file=sys.stderr)
        return 1

    if not args.dry_run:
        _check_tree_clean()
        if not args.allow_non_main:
            _check_branch()

    current = _read_version()
    if not _semver_gt(new_version, current):
        print(f"ERROR: new version {new_version} is not greater than "
              f"current {current}", file=sys.stderr)
        return 1

    print(f"Bumping version: {current} → {new_version}")

    if args.dry_run:
        print("[dry-run] would write _version.py with new version")
        print("[dry-run] would rewrite CHANGELOG.md (Unreleased → "
              f"[{new_version}] - {dt.date.today().isoformat()})")
        print(f"[dry-run] would: git add -A && git commit -m 'release: v{new_version}'")
        print(f"[dry-run] would: git tag v{new_version}")
        print("[dry-run] would: git push origin HEAD --tags")
        return 0

    _bump_version(new_version)
    _bump_changelog(new_version)
    subprocess.check_call(
        ["git", "add", "csm_gui/_version.py", "CHANGELOG.md"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "commit", "-m", f"release: v{new_version}"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "tag", f"v{new_version}"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "push", "origin", "HEAD"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "push", "origin", f"v{new_version}"], cwd=ROOT,
    )
    print(f"\n[OK] Pushed v{new_version}.\n  Watch CI: "
          "https://github.com/<owner>/<repo>/actions  (replace owner/repo)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
