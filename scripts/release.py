"""One-click release: bump version, update CHANGELOG, commit, tag, push.

Tauri stack: the canonical version lives in ``frontend/src-tauri/tauri.conf.json``
(read by the about dialog) and is mirrored in ``frontend/src-tauri/Cargo.toml``
(the Rust crate version — kept in sync so cargo + Tauri metadata don't drift).

Usage:
    python scripts/release.py 0.4.1           # actually do it
    python scripts/release.py 0.4.1 --dry-run # show what would happen

Steps:
    1. Verify git tree clean + on main/master branch
    2. Verify new version > current canonical version and is valid semver
    3. Write tauri.conf.json "version" + Cargo.toml [package].version
    4. Rewrite CHANGELOG.md: rename [Unreleased] → [X.Y.Z] - YYYY-MM-DD
    5. git add + commit + tag + push origin main + push origin <tag>

Note on CHANGELOG flow: this script renames `## [Unreleased]` to
`## [X.Y.Z] - YYYY-MM-DD` without inserting a fresh empty `## [Unreleased]`
above. Add the new `## [Unreleased]` section yourself when starting to
accumulate the next release's entries — keeps it intentional and prevents
stale empty sections from showing up in the release body.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAURI_CONF = ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
CARGO_TOML = ROOT / "frontend" / "src-tauri" / "Cargo.toml"
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


def _read_tauri_version() -> str:
    payload = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    v = payload.get("version")
    if not isinstance(v, str) or not SEMVER_RE.match(v):
        print(f"ERROR: bad 'version' in {TAURI_CONF}: {v!r}", file=sys.stderr)
        sys.exit(1)
    return v


def _bump_tauri_conf(new: str) -> None:
    """Update tauri.conf.json::version preserving 2-space indent.

    json round-trip works here because the file is standard JSON (no
    comments). 2-space indent matches the existing layout.
    """
    payload = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    payload["version"] = new
    TAURI_CONF.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _bump_cargo_toml(new: str) -> None:
    """Rewrite the [package].version line.

    Why regex not toml-edit: stdlib doesn't have a TOML writer and we don't
    want a new dep for one line. Anchored to start-of-line + literal key
    so we won't rewrite a string inside a doc comment.
    """
    text = CARGO_TOML.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        print(f"ERROR: cannot find 'version = \"...\"' in {CARGO_TOML}",
              file=sys.stderr)
        sys.exit(1)
    CARGO_TOML.write_text(new_text, encoding="utf-8")


def _bump_changelog(new: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    today = dt.date.today().isoformat()
    if "## [Unreleased]" not in text:
        print("ERROR: CHANGELOG.md is missing '## [Unreleased]' section",
              file=sys.stderr)
        sys.exit(1)
    text = text.replace(
        "## [Unreleased]",
        f"## [{new}] - {today}",
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
    parser.add_argument("version", help="new version, e.g. 0.4.1")
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

    current = _read_tauri_version()
    if not _semver_gt(new_version, current):
        print(f"ERROR: new version {new_version} is not greater than "
              f"current {current}", file=sys.stderr)
        return 1

    print(f"Bumping version: {current} → {new_version}")

    if args.dry_run:
        print(f"[dry-run] would write {TAURI_CONF} with version={new_version}")
        print(f"[dry-run] would write {CARGO_TOML} with version={new_version}")
        print("[dry-run] would rewrite CHANGELOG.md (Unreleased → "
              f"[{new_version}] - {dt.date.today().isoformat()})")
        print(f"[dry-run] would: git add -A && git commit -m 'release: v{new_version}'")
        print(f"[dry-run] would: git tag v{new_version}")
        print("[dry-run] would: git push origin HEAD --tags")
        return 0

    _bump_tauri_conf(new_version)
    _bump_cargo_toml(new_version)
    _bump_changelog(new_version)
    subprocess.check_call(
        ["git", "add",
         "frontend/src-tauri/tauri.conf.json",
         "frontend/src-tauri/Cargo.toml",
         "CHANGELOG.md"], cwd=ROOT,
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
    print(f"\n[OK] Pushed v{new_version}.")
    print("  Watch CI: https://github.com/zev96/CSM/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
