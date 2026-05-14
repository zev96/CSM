"""Build the standalone updater.exe (PyInstaller onefile).

Usage::

    python scripts/build_updater.py [--clean]

PyInstaller onefile → 单文件 ``updater.exe``，落到
``frontend/src-tauri/binaries/`` 让 ``tauri.conf.json`` 的 ``resources``
能在 bundle 阶段把它打进 NSIS 安装包。

热更新流程下，updater.exe 在主程序退出后接管文件替换 + 重启，所以
跟 csm-sidecar 一样必须是 onefile —— 单 exe 才能脱离主目录在临时位置
执行解压/重命名。

Note: 这个脚本是 release-only 的依赖。dev 模式（``tauri dev``）不需要
跑它 —— Rust 侧的 ``locate_updater_exe`` 找不到时会返回
``updater_not_found``，前端会给友好提示。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATER_DIR = REPO_ROOT / "updater"
SPEC_PATH = UPDATER_DIR / "updater.spec"
DIST_DIR = REPO_ROOT / "frontend" / "src-tauri" / "binaries"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe build/ and dist/ before building.",
    )
    args = parser.parse_args()

    if not SPEC_PATH.exists():
        print(f"[build_updater] spec missing: {SPEC_PATH}", file=sys.stderr)
        return 1

    build_dir = UPDATER_DIR / "build"
    dist_tmp = UPDATER_DIR / "dist"
    if args.clean:
        for p in (build_dir, dist_tmp):
            if p.exists():
                print(f"[build_updater] wiping {p}")
                shutil.rmtree(p)

    print(f"[build_updater] PyInstaller {SPEC_PATH.name}")
    rc = subprocess.call(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC_PATH)],
        cwd=str(UPDATER_DIR),
    )
    if rc != 0:
        print(f"[build_updater] PyInstaller failed ({rc})", file=sys.stderr)
        return rc

    src = dist_tmp / "updater.exe"
    if not src.exists():
        print(f"[build_updater] expected {src} not produced", file=sys.stderr)
        return 2

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = DIST_DIR / "updater.exe"
    shutil.copy2(src, target)
    # ASCII arrow only — Windows CI runners default to cp1252 stdout encoding
    # and `→` (U+2192) crashes with UnicodeEncodeError. Same caution applies
    # to any other script that prints during the release.yml pipeline.
    print(f"[build_updater] copied -> {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
