"""Generate manifest.json from a release zip + version metadata.

Output schema:
    {
      "version": "0.2.0",
      "released_at": "2026-05-07T08:00:00Z",
      "asset_size": 243814092,
      "sha256": "abc123...",
      "min_compatible_version": "0.1.0",  # optional
      "lite": {                            # optional — 增量热更新包（不含 Chromium）
        "asset_name": "CSM-v0.2.0-lite.upd",
        "asset_size": 140000000,
        "sha256": "def456...",
        "chromium_dirs": ["chromium-1181"]
      }
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
    parser.add_argument("--lite-zip", type=Path, default=None,
                        help="增量热更新包（*-lite.upd，不含 binaries/ms-playwright）")
    parser.add_argument("--chromium-dirs", default="",
                        help="完整安装里 binaries/ms-playwright 下的 chromium-XXXX 目录名，"
                             "逗号分隔；客户端本机全部存在才会选增量包")
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

    if args.lite_zip is not None:
        if not args.lite_zip.exists():
            print(f"ERROR: lite zip not found: {args.lite_zip}", file=sys.stderr)
            return 1
        dirs = [d.strip() for d in args.chromium_dirs.split(",") if d.strip()]
        if not dirs:
            print("ERROR: --lite-zip requires --chromium-dirs", file=sys.stderr)
            return 1
        manifest["lite"] = {
            "asset_name": args.lite_zip.name,
            "asset_size": args.lite_zip.stat().st_size,
            "sha256": hashlib.sha256(args.lite_zip.read_bytes()).hexdigest(),
            "chromium_dirs": dirs,
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"OK — wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
