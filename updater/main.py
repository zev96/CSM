"""CSM updater: replace install dir + restart main app.

Spawned by the main CSM process when the user accepts an upgrade. Receives
the main process PID, the downloaded zip path, and the install dir target.
We wait for the main process to exit, then atomically swap the directory.

Usage:
    updater.exe --pid 12345 --zip "C:\\Temp\\CSM-v0.2.0.zip" --target "C:\\Apps\\CSM"
"""
from __future__ import annotations
import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="[updater] %(asctime)s %(levelname)s %(message)s")


def wait_for_pid_exit(pid: int, timeout_s: float = 10.0) -> None:
    """Poll until the OS reports the PID has exited, or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    logger.warning("pid %d still alive after %.1fs — proceeding anyway", pid, timeout_s)


def _pid_alive(pid: int) -> bool:
    """Return True iff a process with that PID is currently alive."""
    if sys.platform.startswith("win"):
        try:
            out = subprocess.check_output(
                ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
                text=True, stderr=subprocess.DEVNULL,
            )
            return str(pid) in out
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False
    # POSIX
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def replace_directory(*, target: Path, zip_path: Path) -> None:
    """Atomically swap the install directory with the contents of ``zip_path``.

    Steps:
        1. Rename target → target.bak
        2. Extract zip to target.parent (zip contains 'CSM/...' tree)
        3. Move extracted dir → target
        4. Remove target.bak

    On any failure, attempt to roll back: remove partial target, restore .bak.
    """
    target = Path(target).resolve()
    zip_path = Path(zip_path).resolve()
    backup = target.with_name(target.name + ".bak")
    extract_root = target.parent

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    # 1. Move current install aside
    if target.exists():
        shutil.move(str(target), str(backup))

    extracted_inner = None
    try:
        # 2. Extract the zip
        with zipfile.ZipFile(zip_path) as zf:
            top_levels = sorted({Path(n).parts[0] for n in zf.namelist() if n})
            zf.extractall(str(extract_root))
        if not top_levels:
            raise RuntimeError("zip is empty")
        extracted_inner = extract_root / top_levels[0]
        if not extracted_inner.exists():
            raise RuntimeError(f"expected {extracted_inner} to exist after extract")

        # 3. Rename extracted dir to target
        if extracted_inner.resolve() != target.resolve():
            shutil.move(str(extracted_inner), str(target))

        # 4. Cleanup .bak
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        logger.exception("replace failed — rolling back")
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        except OSError:
            pass
        if backup.exists():
            try:
                shutil.move(str(backup), str(target))
            except OSError:
                logger.error("rollback failed — install dir may be inconsistent")
        if extracted_inner and extracted_inner.exists() and extracted_inner != target:
            shutil.rmtree(extracted_inner, ignore_errors=True)
        raise


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv[1:])

    logger.info("waiting for main pid %d to exit", args.pid)
    wait_for_pid_exit(args.pid, timeout_s=10)

    try:
        replace_directory(target=args.target, zip_path=args.zip)
    except Exception as e:
        logger.error("update failed: %s", e)
        # Try to relaunch old app via the .bak that we restored
        exe = args.target / "CSM.exe"
        if exe.exists():
            subprocess.Popen([str(exe)], close_fds=True)
        return 1

    # Cleanup downloaded zip
    try:
        args.zip.unlink()
    except OSError:
        pass

    # Relaunch new app
    new_exe = args.target / "CSM.exe"
    if new_exe.exists():
        subprocess.Popen([str(new_exe)], close_fds=True)
        logger.info("relaunched %s", new_exe)
    else:
        logger.warning("new exe not found at %s", new_exe)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
