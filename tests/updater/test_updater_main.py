"""Updater core logic — file replacement + rollback + WebView2 cleanup."""
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


def _make_zip(tmp_path: Path, name: str = "test.zip") -> Path:
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CSM/CSM.exe", "fake new exe content")
        zf.writestr("CSM/data.txt", "new data")
    return z


def test_replace_directory_atomic(tmp_path: Path):
    """replace_directory: backup → extract → move → cleanup."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import replace_directory

    target = tmp_path / "CSM"
    target.mkdir()
    (target / "CSM.exe").write_text("old", encoding="utf-8")

    z = _make_zip(tmp_path)

    replace_directory(target=target, zip_path=z)
    # New content should be in place
    assert (target / "CSM.exe").read_text(encoding="utf-8") == "fake new exe content"
    assert (target / "data.txt").read_text(encoding="utf-8") == "new data"


def test_replace_rolls_back_on_failure(tmp_path: Path, monkeypatch):
    """If extraction or move fails, .bak is restored."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    target = tmp_path / "CSM"
    target.mkdir()
    (target / "CSM.exe").write_text("OLD-CONTENT", encoding="utf-8")
    z = _make_zip(tmp_path)

    # Force the extraction step to fail
    def boom(self, *a, **kw):
        raise OSError("simulated extraction failure")
    monkeypatch.setattr(zipfile.ZipFile, "extractall", boom)

    with pytest.raises(OSError):
        updater_main.replace_directory(target=target, zip_path=z)

    # After rollback, target should still hold old content
    assert (target / "CSM.exe").read_text(encoding="utf-8") == "OLD-CONTENT"


def test_wait_for_pid_exit_returns_quickly_if_not_running(tmp_path: Path):
    """A nonexistent PID should be considered already-exited."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import wait_for_pid_exit
    # 2^32 - 1 is virtually guaranteed not to exist
    wait_for_pid_exit(pid=4294967295, timeout_s=2)  # should return without raising


# ────────────────────────────────────────────────────────────────────────
# v0.5.5 root-cause fix: orphan WebView2 cleanup. These tests守住 the
# invariant that _kill_orphan_webview2 (a) only kills msedgewebview2.exe
# processes, (b) only kills ones whose cmdline references com.csm.app
# (CSM's Tauri identifier), and (c) leaves others alone.
# ────────────────────────────────────────────────────────────────────────


def _fake_proc(pid: int, name: str, cmdline_str: str) -> MagicMock:
    """Build a psutil.Process mock matching .info[...] access pattern."""
    p = MagicMock()
    p.info = {"pid": pid, "name": name, "cmdline": cmdline_str.split()}
    return p


@pytest.mark.skipif(sys.platform != "win32", reason="updater logic is Windows-only")
def test_kill_orphan_webview2_filters_to_csm_identifier(monkeypatch):
    """Only WebView2 procs with com.csm.app in cmdline get killed."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    csm_webview = _fake_proc(
        100, "msedgewebview2.exe",
        '"...\\msedgewebview2.exe" --user-data-dir="C:\\Users\\X\\AppData\\Local\\com.csm.app\\EBWebView"',
    )
    other_webview = _fake_proc(
        200, "msedgewebview2.exe",
        '"...\\msedgewebview2.exe" --user-data-dir="C:\\Users\\X\\AppData\\Local\\com.other.app\\EBWebView"',
    )
    unrelated_chrome = _fake_proc(
        300, "chrome.exe", '"...\\chrome.exe" https://example.com',
    )

    fake_psutil = MagicMock()
    fake_psutil.process_iter.return_value = [csm_webview, other_webview, unrelated_chrome]
    # The real psutil module exports NoSuchProcess / AccessDenied — keep them
    # as harmless attributes so the except clauses inside _kill_orphan_webview2
    # don't trip on the mock module.
    fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    killed = updater_main._kill_orphan_webview2()

    assert killed == 1, "exactly one (CSM-identified) webview2 should be killed"
    csm_webview.kill.assert_called_once()
    other_webview.kill.assert_not_called(), "other Tauri app's WebView2 must not be killed"
    unrelated_chrome.kill.assert_not_called(), "Chrome is not WebView2 — must not be touched"


@pytest.mark.skipif(sys.platform != "win32", reason="updater logic is Windows-only")
def test_kill_orphan_webview2_handles_missing_psutil(monkeypatch):
    """If psutil isn't importable, log a warning and return 0 instead of crashing."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    # Force `import psutil` inside the function to raise ImportError.
    monkeypatch.setitem(sys.modules, "psutil", None)

    killed = updater_main._kill_orphan_webview2()

    assert killed == 0


def test_kill_orphan_webview2_noop_on_non_windows(monkeypatch):
    """On POSIX, function returns 0 immediately without touching psutil."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    monkeypatch.setattr(sys, "platform", "linux")
    # If psutil were touched, this stub would raise — but it shouldn't be touched.
    monkeypatch.setitem(
        sys.modules, "psutil",
        MagicMock(process_iter=MagicMock(side_effect=AssertionError("should not call")))
    )

    killed = updater_main._kill_orphan_webview2()

    assert killed == 0


def test_csm_tauri_identifier_matches_tauri_config():
    """``CSM_TAURI_IDENTIFIER`` must match ``tauri.conf.json::identifier``
    so the cmdline filter actually identifies CSM's WebView2 children.

    If this fires, someone changed the Tauri identifier without updating
    the updater's filter — orphan cleanup will silently miss every
    WebView2 child and the install-dir rename will lock again.
    """
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import CSM_TAURI_IDENTIFIER

    tauri_conf = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "src-tauri" / "tauri.conf.json"
    )
    payload = json.loads(tauri_conf.read_text(encoding="utf-8"))
    assert payload["identifier"] == CSM_TAURI_IDENTIFIER, (
        f"tauri.conf.json identifier {payload['identifier']!r} != "
        f"updater's CSM_TAURI_IDENTIFIER {CSM_TAURI_IDENTIFIER!r}"
    )


def test_main_chdirs_to_temp_first_thing(monkeypatch, tmp_path):
    """main() must chdir to temp before parsing args.

    Defense-in-depth against a future spawner that forgets to set cwd.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    chdir_calls = []
    monkeypatch.setattr("os.chdir", lambda p: chdir_calls.append(p))

    # ArgumentParser raises SystemExit on missing required args — that's
    # fine for this test, we just need to observe chdir was called first.
    try:
        updater_main.main(["updater.exe"])  # no --pid / --zip / --target
    except SystemExit:
        pass

    assert chdir_calls, "main() must call os.chdir before parsing args"
    import tempfile as _tempfile
    assert chdir_calls[0] == _tempfile.gettempdir(), (
        f"first chdir target was {chdir_calls[0]!r}, expected tempdir"
    )


# ── 增量包：binaries/ms-playwright 从旧安装搬进新树 ───────────────────────────
def _make_lite_zip(tmp_path: Path, name: str = "lite.upd") -> Path:
    """增量包：没有 CSM/binaries/ms-playwright/ 任何条目。"""
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CSM/CSM.exe", "new exe (lite)")
        zf.writestr("CSM/binaries/updater.exe", "new updater")
    return z


def _seed_install_with_chromium(tmp_path: Path) -> Path:
    target = tmp_path / "CSM"
    chrome = target / "binaries" / "ms-playwright" / "chromium-1181"
    chrome.mkdir(parents=True)
    (chrome / "chrome.exe").write_text("chromium bytes", encoding="utf-8")
    (target / "CSM.exe").write_text("OLD-CONTENT", encoding="utf-8")
    return target


def test_lite_zip_carries_chromium_from_old_install(tmp_path: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import replace_directory

    target = _seed_install_with_chromium(tmp_path)
    replace_directory(target=target, zip_path=_make_lite_zip(tmp_path))

    assert (target / "CSM.exe").read_text(encoding="utf-8") == "new exe (lite)"
    assert (target / "binaries" / "updater.exe").read_text(encoding="utf-8") == "new updater"
    chrome = target / "binaries" / "ms-playwright" / "chromium-1181" / "chrome.exe"
    assert chrome.read_text(encoding="utf-8") == "chromium bytes"
    assert not (tmp_path / "CSM.bak").exists()
    assert not (tmp_path / ".CSM.upd").exists()


def test_full_zip_replaces_chromium_instead_of_carrying(tmp_path: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import replace_directory

    target = _seed_install_with_chromium(tmp_path)
    z = tmp_path / "full.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CSM/CSM.exe", "new exe (full)")
        zf.writestr("CSM/binaries/ms-playwright/chromium-1200/chrome.exe", "newer chromium")
    replace_directory(target=target, zip_path=z)

    pw = target / "binaries" / "ms-playwright"
    assert (pw / "chromium-1200" / "chrome.exe").read_text(encoding="utf-8") == "newer chromium"
    assert not (pw / "chromium-1181").exists()  # 完整包以自己的为准，旧内核不保留


def test_lite_rollback_puts_chromium_back(tmp_path: Path, monkeypatch):
    """最后一步 extracted → target 改名失败：回滚后旧安装完整，包括已经搬走的 Chromium。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    target = _seed_install_with_chromium(tmp_path)
    resolved_target = target.resolve()
    real_rename = updater_main._rename_retry

    def flaky_rename(src, dst, **kw):
        if Path(dst) == resolved_target and Path(src).name != "CSM.bak":
            raise OSError("simulated: target locked")
        return real_rename(src, dst, **kw)

    monkeypatch.setattr(updater_main, "_rename_retry", flaky_rename)
    with pytest.raises(OSError):
        updater_main.replace_directory(target=target, zip_path=_make_lite_zip(tmp_path))

    assert (target / "CSM.exe").read_text(encoding="utf-8") == "OLD-CONTENT"
    chrome = target / "binaries" / "ms-playwright" / "chromium-1181" / "chrome.exe"
    assert chrome.read_text(encoding="utf-8") == "chromium bytes"
    assert not (tmp_path / "CSM.bak").exists()
