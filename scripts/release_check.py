"""CI guard: verify the git tag being released matches csm_gui._version.__version__.

Usage:
    python scripts/release_check.py <tag-or-version>

Examples:
    python scripts/release_check.py v0.2.0
    python scripts/release_check.py 0.2.0   # v-prefix optional
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Inject project root into path so we can import csm_gui without installing.
sys.path.insert(0, str(ROOT))

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


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
        from csm_gui._version import __version__
    except ImportError as e:
        print(f"ERROR: cannot import csm_gui._version: {e}", file=sys.stderr)
        return 1

    if tag_version != __version__:
        print(
            f"ERROR: tag/version mismatch — argument='{raw}' "
            f"(parsed={tag_version}) != __version__='{__version__}'",
            file=sys.stderr,
        )
        return 1

    print(f"OK — tag {raw} matches __version__ {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
