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
import tempfile
import time
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Tauri identifier — appears in WebView2 children's cmdline via the
# ``--user-data-dir=...\com.csm.app\EBWebView`` flag. Used to filter
# CSM's WebView2 processes out of all running msedgewebview2.exe on
# the system (don't kill other Tauri/Electron apps).
CSM_TAURI_IDENTIFIER = "com.csm.app"


def _setup_logging() -> Path | None:
    """Set up console + file logging. Log file goes next to the target so
    users can find it easily when something goes wrong.
    """
    log_path: Path | None = None
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    # Try to add a file handler to %TEMP%\csm_update\updater.log so logs
    # survive after the console window closes.
    try:
        log_dir = Path(os.environ.get("TEMP", ".")) / "csm_update"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "updater.log"
        fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        handlers.append(fh)
    except Exception:
        pass
    logging.basicConfig(
        level=logging.DEBUG,
        format="[updater] %(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    return log_path


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


def _kill_orphan_webview2() -> int:
    """Kill orphan ``msedgewebview2.exe`` processes spawned by CSM.

    Why: WebView2 child processes spawned by csm-tauri inherit cwd
    = install dir (Tauri 2 doesn't bind them to a Win32 Job Object, and
    csm-tauri itself doesn't ``current_dir`` away before spawning them).
    When csm-tauri exits via ``app.exit(0)`` right before updater runs,
    these WebView2 children survive as orphans whose ParentProcessId
    points to a dead pid — ``taskkill /T`` can't reach them. Their cwd
    handles keep the install dir from being renamed (v0.5.4 and earlier
    saw WinError 32 here even after csm-* was taskkilled).

    Filter by ``CSM_TAURI_IDENTIFIER`` (``com.csm.app``) appearing in
    cmdline so we don't kill WebView2 processes belonging to other
    Tauri/Electron apps the user might have running. The identifier
    appears in every CSM WebView2 child's ``--user-data-dir=...`` flag.

    Returns the number of processes killed. No-op on non-Windows or when
    psutil is unavailable.
    """
    if not sys.platform.startswith("win"):
        return 0
    try:
        import psutil
    except ImportError:
        logger.warning(
            "psutil not bundled with updater; skipping orphan WebView2 cleanup "
            "(install dir may stay locked by orphans)"
        )
        return 0

    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] != "msedgewebview2.exe":
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if CSM_TAURI_IDENTIFIER not in cmdline:
                continue
            proc.kill()
            killed += 1
            logger.info("killed orphan webview2 pid=%d", proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception as e:
            logger.warning(
                "failed to kill webview2 pid=%s: %s",
                proc.info.get("pid"), e,
            )
    logger.info("orphan webview2 cleanup: killed %d", killed)
    return killed


def _taskkill_csm_processes() -> None:
    """Defensive kill of any leftover csm-sidecar.exe / csm-tauri.exe + orphan WebView2.

    Tauri's sidecar lifecycle doesn't reliably propagate close to the child
    csm-sidecar.exe when the main process exits — sidecar then keeps a lock
    on ``<install>/csm-sidecar.exe`` (and on data-dir files), which makes the
    rename in ``replace_directory`` fail with WinError 32. WebView2 children
    are even worse: they outlive csm-tauri as orphans (see
    :func:`_kill_orphan_webview2`). Mirrors the NSIS PREINSTALL hook in
    ``frontend/src-tauri/installer-hooks.nsh``.

    No-op on non-Windows. taskkill exit code is ignored (process may already
    be gone, which we want).
    """
    if not sys.platform.startswith("win"):
        return
    for name in ("csm-sidecar.exe", "csm-tauri.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", name, "/T"],
                timeout=10,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            logger.info("taskkill /F /IM %s issued", name)
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("taskkill %s failed: %s", name, e)
    # WebView2 children are not named csm-*, so taskkill above misses them.
    # Clean them up explicitly — this is the v0.5.5 root-cause fix.
    _kill_orphan_webview2()
    # Give Windows time to release file handles after process exit.
    time.sleep(0.5)


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
    log_path = _setup_logging()

    # CRITICAL — chdir away from install dir before doing anything.
    #
    # When updater.exe is spawned by csm-tauri without an explicit
    # ``current_dir``, it inherits the parent's cwd (= install dir on
    # double-click launches where NSIS shortcut sets cwd to install dir).
    # Our own cwd handle on install dir then blocks the rename below.
    # Rust-side spawning was fixed in v0.5.5 (updater.rs sets
    # current_dir(temp_dir)), but this chdir is a defense-in-depth so
    # any spawner that forgets to set cwd still doesn't lock us.
    try:
        os.chdir(tempfile.gettempdir())
    except OSError as e:
        logger.warning(
            "chdir to %s failed: %s — install dir rename may fail under cwd lock",
            tempfile.gettempdir(), e,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--keep-window", action="store_true",
                        help="keep the console window open after finishing")
    args = parser.parse_args(argv[1:])

    logger.info("=" * 60)
    logger.info("CSM updater starting")
    logger.info("  --pid    = %d", args.pid)
    logger.info("  --zip    = %s (exists=%s, size=%s)",
                args.zip, args.zip.exists(),
                args.zip.stat().st_size if args.zip.exists() else "n/a")
    logger.info("  --target = %s (exists=%s)",
                args.target, args.target.exists())
    if log_path:
        logger.info("  log file = %s", log_path)
    logger.info("=" * 60)

    logger.info("waiting for main pid %d to exit", args.pid)
    wait_for_pid_exit(args.pid, timeout_s=10)
    logger.info("main pid exited (or timeout passed)")

    # Even after main (csm-tauri) exits, csm-sidecar.exe often outlives it
    # briefly because Tauri's sidecar lifecycle doesn't always propagate the
    # close signal. The sidecar then holds a lock on <install>/csm-sidecar.exe
    # and blocks the rename below. Match the NSIS PREINSTALL hook's behavior.
    _taskkill_csm_processes()

    success = False
    try:
        replace_directory(target=args.target, zip_path=args.zip)
        success = True
        logger.info("replace_directory OK")
    except Exception as e:
        logger.exception("update failed: %s", e)

    # Cleanup downloaded zip on success only — keep it for debugging on failure.
    if success:
        try:
            args.zip.unlink()
            logger.info("cleaned up zip %s", args.zip)
        except OSError as e:
            logger.warning("failed to clean zip: %s", e)

    # Relaunch (whether new or old after rollback).
    # 主 exe 实际名字是 csm-tauri.exe（Cargo [[bin]].name 决定的），不是
    # productName "CSM"。保留 CSM.exe 兜底以防将来改 Cargo 名。
    candidates = [args.target / "csm-tauri.exe", args.target / "CSM.exe"]
    new_exe = next((c for c in candidates if c.exists()), None)
    if new_exe is not None:
        logger.info("relaunching %s", new_exe)
        subprocess.Popen([str(new_exe)], close_fds=True)
    else:
        logger.error(
            "no known main exe found in %s (tried %s) — cannot relaunch",
            args.target, [c.name for c in candidates],
        )

    # Keep window open if --keep-window AND we have a console attached.
    # PyInstaller 'windowed' build (console=False) has no stdin — input()
    # would block forever with no way to dismiss. Detect via sys.stdin
    # being a real tty / non-null; on windowed builds Python sets stdin
    # to a closed file-like that throws on read.
    has_console = sys.stdin is not None and not sys.stdin.closed
    if args.keep_window and has_console:
        logger.info("=" * 60)
        logger.info(
            "%s — press Enter to close.",
            "Update succeeded" if success else "UPDATE FAILED — see log above",
        )
        try:
            input()
        except (EOFError, KeyboardInterrupt, OSError):
            pass

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
