"""CI guard: verify the git tag being released matches the canonical version.

Source of truth is ``frontend/src-tauri/tauri.conf.json`` (the Tauri shell's
``version`` field). The legacy ``csm_gui/_version.py`` is no longer read here —
it's still in the repo for the deprecated PyQt6 GUI but isn't shipped.

Usage:
    python scripts/release_check.py <tag-or-version>

Examples:
    python scripts/release_check.py v0.4.1
    python scripts/release_check.py 0.4.1   # v-prefix optional
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAURI_CONF = ROOT / "frontend" / "src-tauri" / "tauri.conf.json"

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


def _read_tauri_version() -> str:
    """Pull the ``version`` field from tauri.conf.json (raises on missing)."""
    if not TAURI_CONF.exists():
        raise FileNotFoundError(f"tauri.conf.json not found: {TAURI_CONF}")
    payload = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    v = payload.get("version")
    if not v or not isinstance(v, str):
        raise ValueError(f"'version' field missing or non-string in {TAURI_CONF}")
    return v


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: release_check.py <tag-or-version>", file=sys.stderr)
        return 2

    raw = argv[1]
    m = SEMVER_RE.match(raw)
    if not m:
        print(f"ERROR: '{raw}' is not a valid semver tag (expected vX.Y.Z)",
              file=sys.stderr)
        return 1
    tag_version = ".".join(m.group(1, 2, 3))

    try:
        canonical = _read_tauri_version()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read canonical version: {e}", file=sys.stderr)
        return 1

    if tag_version != canonical:
        print(
            f"ERROR: tag/version mismatch — argument='{raw}' "
            f"(parsed={tag_version}) != tauri.conf.json version='{canonical}'",
            file=sys.stderr,
        )
        return 1

    print(f"OK — tag {raw} matches tauri.conf.json version {canonical}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
