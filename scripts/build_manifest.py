"""Generate manifest.json from a release zip + version metadata.

Output schema:
    {
      "version": "0.2.0",
      "released_at": "2026-05-07T08:00:00Z",
      "asset_size": 243814092,
      "sha256": "abc123...",
      "min_compatible_version": "0.1.0"   # optional
    }

CI uploads this manifest alongside the zip in the GitHub Release.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="e.g. 0.2.0")
    parser.add_argument("--zip", required=True, type=Path,
                        help="path to the release zip")
    parser.add_argument("--out", required=True, type=Path,
                        help="output manifest.json path")
    parser.add_argument("--min-compatible", default=None,
                        help="optional minimum-compatible version")
    args = parser.parse_args(argv[1:])

    if not args.zip.exists():
        print(f"ERROR: zip not found: {args.zip}", file=sys.stderr)
        return 1

    sha = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    size = args.zip.stat().st_size

    manifest = {
        "version": args.version.lstrip("v"),
        "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                                                 .replace("+00:00", "Z"),
        "asset_size": size,
        "sha256": sha,
    }
    if args.min_compatible:
        manifest["min_compatible_version"] = args.min_compatible.lstrip("v")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"OK — wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
