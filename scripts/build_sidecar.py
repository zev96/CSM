"""Build the csm-sidecar PyInstaller bundle.

Usage:

    python scripts/build_sidecar.py [--clean] [--target-triple <triple>]

Produces ``frontend/src-tauri/binaries/csm-sidecar/`` (a directory). When
``--target-triple`` is given (e.g. ``x86_64-pc-windows-msvc``), the output
folder is renamed to ``csm-sidecar-<triple>`` to match Tauri's
``externalBin`` lookup convention. Tauri also expects the actual EXE
inside that folder to carry the same triple suffix —
``csm-sidecar-<triple>.exe`` — so we rename that too.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DIR = REPO_ROOT / "sidecar"
SPEC_PATH = SIDECAR_DIR / "csm-sidecar.spec"
DEFAULT_DIST = REPO_ROOT / "frontend" / "src-tauri" / "binaries"


def detect_target_triple() -> str:
    """Match Tauri's host-triple naming so externalBin resolution works."""
    sys_name = platform.system().lower()
    arch = platform.machine().lower()
    if sys_name == "windows":
        return f"{'aarch64' if arch in ('arm64', 'aarch64') else 'x86_64'}-pc-windows-msvc"
    if sys_name == "darwin":
        return f"{'aarch64' if arch in ('arm64', 'aarch64') else 'x86_64'}-apple-darwin"
    return f"{'aarch64' if arch in ('aarch64',) else 'x86_64'}-unknown-linux-gnu"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe build/ and dist/ before building.",
    )
    parser.add_argument(
        "--target-triple",
        default=detect_target_triple(),
        help="Tauri host triple to embed in the output folder name.",
    )
    parser.add_argument(
        "--distpath",
        default=str(DEFAULT_DIST),
        help="Where the onedir bundle lands. Defaults to Tauri's externalBin dir.",
    )
    args = parser.parse_args()

    if not SPEC_PATH.exists():
        print(f"missing spec: {SPEC_PATH}", file=sys.stderr)
        return 2

    if args.clean:
        for p in (SIDECAR_DIR / "build", SIDECAR_DIR / "dist"):
            if p.exists():
                print(f"  [clean] removing {p}")
                shutil.rmtree(p, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_PATH),
        "--noconfirm",
        "--distpath",
        args.distpath,
    ]
    print(f"  $ {' '.join(cmd)}")
    rc = subprocess.call(cmd, cwd=str(SIDECAR_DIR))
    if rc != 0:
        return rc

    # Rename to <name>-<triple>/<name>-<triple>.exe for Tauri's externalBin.
    out_dir = Path(args.distpath) / "csm-sidecar"
    if not out_dir.exists():
        print(f"build succeeded but {out_dir} not found", file=sys.stderr)
        return 3

    suffixed_dir = Path(args.distpath) / f"csm-sidecar-{args.target_triple}"
    if suffixed_dir.exists():
        shutil.rmtree(suffixed_dir, ignore_errors=True)
    out_dir.rename(suffixed_dir)

    exe_name = "csm-sidecar.exe" if platform.system() == "Windows" else "csm-sidecar"
    src_exe = suffixed_dir / exe_name
    if src_exe.exists():
        if platform.system() == "Windows":
            dst_exe = suffixed_dir / f"csm-sidecar-{args.target_triple}.exe"
        else:
            dst_exe = suffixed_dir / f"csm-sidecar-{args.target_triple}"
        if dst_exe.exists():
            dst_exe.unlink()
        src_exe.rename(dst_exe)

    # Flatten: Tauri's externalBin lookup wants the .exe directly at
    # binaries/csm-sidecar-<triple>.exe, but PyInstaller onedir produces
    # binaries/csm-sidecar-<triple>/{exe + _internal/}. Move both up so
    # both Tauri's externalBin (looks for the .exe) and PyInstaller's
    # _MEIPASS lookup (looks for sibling _internal/) are happy.
    final_exe = Path(args.distpath) / (
        f"csm-sidecar-{args.target_triple}.exe"
        if platform.system() == "Windows"
        else f"csm-sidecar-{args.target_triple}"
    )
    final_internal = Path(args.distpath) / "_internal"
    if final_exe.exists():
        final_exe.unlink()
    if final_internal.exists():
        shutil.rmtree(final_internal, ignore_errors=True)
    inner_exe = suffixed_dir / final_exe.name
    inner_internal = suffixed_dir / "_internal"
    inner_exe.rename(final_exe)
    inner_internal.rename(final_internal)
    suffixed_dir.rmdir()

    # Sync _internal/ into Cargo's dev/release output dirs so `tauri:dev`
    # works without a separate copy step. Cargo only copies the bare .exe
    # listed in externalBin, but PyInstaller onedir needs _internal/
    # alongside it to load python<ver>.dll. Without this, the spawned
    # sidecar exits instantly (no logs, no port) and every API call falls
    # over with connection-refused.
    repo_root = Path(args.distpath).resolve().parent.parent
    target_dir = repo_root / "src-tauri" / "target"
    for variant in ("debug", "release"):
        cargo_dir = target_dir / variant
        if not cargo_dir.exists():
            continue
        # Tauri dev copies the exe stripped of the triple suffix.
        cargo_exe = cargo_dir / (
            "csm-sidecar.exe" if platform.system() == "Windows" else "csm-sidecar"
        )
        cargo_internal = cargo_dir / "_internal"
        # Refresh: remove stale, copy fresh. Use copy not move so the
        # canonical copy under binaries/ stays the bundle source.
        # dirs_exist_ok=True so we don't fail if Tauri is running and
        # has some _internal/ files open — copytree just overlays them.
        try:
            shutil.copytree(final_internal, cargo_internal, dirs_exist_ok=True)
            if cargo_exe.exists():
                try:
                    cargo_exe.unlink()
                except PermissionError:
                    pass  # csm-tauri may have the exe mapped; leave old copy
            shutil.copy2(final_exe, cargo_exe)
            print(f"  sync  {cargo_dir}/  (exe + _internal/)")
        except (PermissionError, OSError) as e:
            print(
                f"  skip-sync {cargo_dir}/ — close Tauri first then rerun "
                f"this script ({e.__class__.__name__})"
            )

    print(f"\n  ok  {final_exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
