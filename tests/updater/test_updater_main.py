"""Updater core logic — file replacement + rollback."""
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch
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
