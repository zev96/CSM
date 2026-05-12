"""Build the csm-sidecar PyInstaller bundle.

Usage:

    python scripts/build_sidecar.py [--clean] [--target-triple <triple>]

PyInstaller onefile mode → produces a single ``csm-sidecar.exe`` at
``frontend/src-tauri/binaries/``. We just rename it with Tauri's host
triple suffix (e.g. ``csm-sidecar-x86_64-pc-windows-msvc.exe``) so the
``externalBin: ["binaries/csm-sidecar"]`` lookup resolves cleanly, then
sync it to ``src-tauri/target/{debug,release}/`` for ``tauri dev``.

历史包袱：这个脚本以前是为 onedir 写的，会处理 ``_internal/`` 目录的
移动、flatten、双向同步。切回 onefile 之后那一堆代码全删 —— 单文件
连 Tauri 一起 bundle 即可，无依赖外联。
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
        help="Where the onefile exe lands. Defaults to Tauri's externalBin dir.",
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
        # 顺手清掉旧 onedir 残留的 _internal/，否则 Tauri 还会去 bundle 它
        legacy_internal = Path(args.distpath) / "_internal"
        if legacy_internal.exists():
            print(f"  [clean] removing legacy onedir folder {legacy_internal}")
            shutil.rmtree(legacy_internal, ignore_errors=True)

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

    # onefile 模式下 PyInstaller 直接产出 <distpath>/csm-sidecar.exe（单文件）。
    # 重命名为带 host-triple 后缀的形式，让 Tauri 的 externalBin: ["binaries/csm-sidecar"]
    # 自动解析。
    exe_name = "csm-sidecar.exe" if platform.system() == "Windows" else "csm-sidecar"
    src_exe = Path(args.distpath) / exe_name
    if not src_exe.exists():
        print(f"build succeeded but {src_exe} not found", file=sys.stderr)
        return 3

    final_exe_name = (
        f"csm-sidecar-{args.target_triple}.exe"
        if platform.system() == "Windows"
        else f"csm-sidecar-{args.target_triple}"
    )
    final_exe = Path(args.distpath) / final_exe_name
    if final_exe.exists():
        final_exe.unlink()
    src_exe.rename(final_exe)

    # 同步到 Cargo 的 target/{debug,release}/，让 `tauri dev` 能直接找到
    # 单文件 sidecar。无需再 copy _internal/。
    repo_root = Path(args.distpath).resolve().parent.parent
    target_dir = repo_root / "src-tauri" / "target"
    cargo_exe_basename = (
        "csm-sidecar.exe" if platform.system() == "Windows" else "csm-sidecar"
    )
    for variant in ("debug", "release"):
        cargo_dir = target_dir / variant
        if not cargo_dir.exists():
            continue
        cargo_exe = cargo_dir / cargo_exe_basename
        try:
            if cargo_exe.exists():
                try:
                    cargo_exe.unlink()
                except PermissionError:
                    pass  # csm-tauri may have the exe mapped; leave old copy
            shutil.copy2(final_exe, cargo_exe)
            # 顺手清掉旧 onedir 残留
            stale_internal = cargo_dir / "_internal"
            if stale_internal.exists():
                shutil.rmtree(stale_internal, ignore_errors=True)
                print(f"  cleaned legacy {stale_internal}")
            print(f"  sync  {cargo_dir}/  (onefile exe)")
        except (PermissionError, OSError) as e:
            print(
                f"  skip-sync {cargo_dir}/ — close Tauri first then rerun "
                f"this script ({e.__class__.__name__})"
            )

    print(f"\n  ok  {final_exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
