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


def _rmtree_retry(path: Path, max_attempts: int = 8, delay: float = 0.5) -> None:
    """rmtree with retry. Windows can hold file locks for several seconds
    after the source process exits — DLLs in particular have lazy-release
    semantics. Each attempt waits longer than the last.
    """
    p = Path(path)
    if not p.exists():
        return
    last_exc: Exception | None = None
    for i in range(max_attempts):
        try:
            shutil.rmtree(str(p))
            return
        except OSError as e:
            last_exc = e
            time.sleep(delay * (i + 1))
    logger.warning("rmtree %s failed after %d attempts: %s",
                   p, max_attempts, last_exc)
    # Don't raise — caller decides if missing cleanup is fatal.


def _rename_retry(src: Path, dst: Path,
                  max_attempts: int = 8, delay: float = 0.5) -> None:
    """os.rename with retry for Windows file lock tolerance."""
    last_exc: Exception | None = None
    for i in range(max_attempts):
        try:
            os.rename(str(src), str(dst))
            return
        except OSError as e:
            last_exc = e
            time.sleep(delay * (i + 1))
    if last_exc:
        raise last_exc


def replace_directory(*, target: Path, zip_path: Path) -> None:
    """Swap the install directory with the contents of ``zip_path``.

    Strategy (order matters — keeps live install untouched until ready):
        1. Extract zip into a sibling temp dir (``.<name>.upd``).
           Failures here don't touch the live install.
        2. Verify extracted dir has expected top-level layout.
        3. Rename target → target.bak (atomic on same volume).
        4. Rename extracted/<top> → target (atomic).
        5. Remove tmp + backup with retry (Windows file-lock tolerance).

    Rollback semantics: any failure during steps 3-4 restores the .bak.
    Failures in steps 1-2 leave the live install untouched.
    """
    target = Path(target).resolve()
    zip_path = Path(zip_path).resolve()
    parent = target.parent
    backup = target.with_name(target.name + ".bak")
    tmp_extract = parent / f".{target.name}.upd"

    # Clean any leftover artifacts from a previous interrupted run.
    if tmp_extract.exists():
        _rmtree_retry(tmp_extract)
    if backup.exists():
        _rmtree_retry(backup)

    # 1. Extract zip to tmp dir.
    tmp_extract.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            top_levels = sorted(
                {Path(n).parts[0] for n in zf.namelist() if n}
            )
            if not top_levels:
                raise RuntimeError("zip is empty")
            zf.extractall(str(tmp_extract))
    except Exception:
        _rmtree_retry(tmp_extract)
        raise

    extracted_inner = tmp_extract / top_levels[0]
    if not extracted_inner.exists():
        _rmtree_retry(tmp_extract)
        raise RuntimeError(
            f"expected {extracted_inner} to exist after extract"
        )

    # 2. Move target → backup (with retry on locked DLLs).
    if target.exists():
        try:
            _rename_retry(target, backup)
        except OSError as e:
            logger.error("could not rename target → backup: %s", e)
            _rmtree_retry(tmp_extract)
            raise

    # 3. Move extracted/<top> → target (atomic on same volume).
    try:
        _rename_retry(extracted_inner, target)
    except Exception:
        logger.exception("move new → target failed; rolling back")
        # Live install was already moved to backup; restore it.
        if target.exists():
            _rmtree_retry(target)
        if backup.exists():
            try:
                os.rename(str(backup), str(target))
            except OSError:
                logger.error(
                    "rollback rename failed — install may be inconsistent"
                )
        _rmtree_retry(tmp_extract)
        raise

    # 4. Cleanup tmp + backup. ``_rmtree_retry`` swallows persistent failures
    # so a stuck .bak doesn't break the relaunch — user can clean up manually.
    _rmtree_retry(tmp_extract)
    _rmtree_retry(backup)


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
