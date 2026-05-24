"""v0.5.6 root-cause fixes for the mining bundle bugs:

1. ``csm-sidecar.spec`` was missing the catch-all ``collect_data_files``
   for ``csm_core`` — ``mc_kuaishou_search.graphql`` (and any future
   non-Python data file under csm_core) didn't make it into the
   PyInstaller bundle, so the runtime ``_QUERY_TEMPLATE_PATH.read_text()``
   crashed with FileNotFoundError on every kuaishou search task.

2. ``douyin_search`` bailed out the moment ``_risk.detect`` flagged a
   captcha — the user had no chance to solve the puzzle in the visible
   browser. Now we poll up to 5 min for the page to clear before bailing.

These tests守住 the fixes — if either regresses, the relevant assertion
fires before anyone ships a broken bundle to users.
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── spec / bundle invariants ──────────────────────────────────────────


def test_kuaishou_graphql_template_file_exists():
    """Sanity: the vendored GraphQL template must exist in the source tree.

    If this fires, the bug is "file was deleted", not "spec misconfigured".
    """
    from csm_core.mining.platforms.kuaishou_search import _QUERY_TEMPLATE_PATH

    assert _QUERY_TEMPLATE_PATH.exists(), (
        f"vendored GraphQL template missing on disk: {_QUERY_TEMPLATE_PATH} — "
        "this is the file that kuaishou_search reads at runtime"
    )
    content = _QUERY_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert content.strip(), "GraphQL template is empty"
    assert "visionSearchPhoto" in content, (
        "GraphQL template doesn't look like the kuaishou search query "
        "(expected 'visionSearchPhoto' operation name)"
    )


def test_sidecar_spec_collects_csm_core_non_py_data():
    """v0.5.6 fix invariant: csm-sidecar.spec must call ``collect_data_files``
    on the ``csm_core`` package, otherwise non-Python data files
    (``.graphql``, future ``.json``/``.yaml`` configs, etc.) silently fall
    out of the PyInstaller bundle.

    History: kuaishou_search.py started reading
    ``_vendor/mc_kuaishou_search.graphql`` in v0.5.0 but the spec never
    listed it. The bundle shipped with an empty ``_vendor/``, and every
    kuaishou search blew up at runtime with FileNotFoundError from v0.5.0
    through v0.5.5 — five releases of the same broken bundle. The
    catch-all here makes "forgot to update the spec" structurally
    impossible for future data files.
    """
    spec_path = REPO_ROOT / "sidecar" / "csm-sidecar.spec"
    spec_text = spec_path.read_text(encoding="utf-8")

    assert "collect_data_files(\"csm_core\"" in spec_text, (
        f"{spec_path} missing collect_data_files(\"csm_core\", ...) — "
        "the catch-all that ensures every non-Python file under csm_core "
        "lands in the PyInstaller bundle. Without it, dropping a new "
        "config/template/fixture file into csm_core silently breaks the "
        "release bundle (the v0.5.0–v0.5.5 mc_kuaishou_search.graphql bug)."
    )


# ── douyin captcha-wait loop ──────────────────────────────────────────
#
# We can't spin up a real Patchright page in unit tests, so the helper
# ``_wait_for_captcha_cleared`` was extracted to take a generic ``page``
# object (only used as the argument to ``_risk.detect``). Mocking
# ``_risk.detect`` lets us drive the polling loop deterministically.


@pytest.fixture
def fake_progress():
    """Capture every ProgressUpdate the adapter emits."""
    calls = []

    def _record(pu):
        calls.append(pu)

    return _record, calls


def test_captcha_wait_resolves_when_risk_clears(fake_progress, monkeypatch):
    """When the user solves the captcha within the timeout, the helper
    returns True and emits a ``captcha_waiting`` progress update.

    Drives the polling loop: ``_risk.detect`` returns True once (initial
    check), then False on the next poll. Sleep is patched to a no-op so
    the test doesn't actually wait 3 seconds.
    """
    from csm_core.mining.platforms import douyin_search

    on_progress, progress_calls = fake_progress
    cancel = threading.Event()

    detect_results = [True, False]  # detect_signal returns truthy → wait → next poll clears
    monkeypatch.setattr(
        douyin_search._risk, "detect",
        lambda page, response=None: detect_results.pop(0) if detect_results else False,
    )
    monkeypatch.setattr(
        douyin_search._risk, "detect_signal",
        lambda page, response=None: type("S", (), {"layer": "dom"})(),
    )
    monkeypatch.setattr(douyin_search.time, "sleep", lambda _s: None)

    result = douyin_search._wait_for_captcha_cleared(
        page=None, on_progress=on_progress, cancel_event=cancel,
        emitted=12, target_count=50, platform="douyin",
    )

    assert result is True, "helper should return True when captcha clears"
    assert any(pu.phase == "captcha_waiting" for pu in progress_calls), (
        "must emit at least one captcha_waiting ProgressUpdate so the UI "
        "can show the 'needs verification' chip while waiting"
    )
    waiting = next(pu for pu in progress_calls if pu.phase == "captcha_waiting")
    assert waiting.note, "captcha_waiting update must carry a user-facing note"
    assert "浏览器" in waiting.note or "验证" in waiting.note, (
        f"note should explain the user's expected action, got: {waiting.note!r}"
    )


def test_captcha_wait_returns_false_on_cancel(fake_progress, monkeypatch):
    """User pressing ⏹ stops the wait immediately."""
    from csm_core.mining.platforms import douyin_search

    on_progress, _ = fake_progress
    cancel = threading.Event()
    cancel.set()  # already cancelled before we even start polling

    monkeypatch.setattr(
        douyin_search._risk, "detect", lambda page, response=None: True,
    )
    monkeypatch.setattr(
        douyin_search._risk, "detect_signal",
        lambda page, response=None: type("S", (), {"layer": "url"})(),
    )
    monkeypatch.setattr(douyin_search.time, "sleep", lambda _s: None)

    result = douyin_search._wait_for_captcha_cleared(
        page=None, on_progress=on_progress, cancel_event=cancel,
        emitted=0, target_count=50, platform="douyin",
    )

    assert result is False, "helper should bail when cancel_event is set"


def test_captcha_wait_returns_false_on_timeout(fake_progress, monkeypatch):
    """If _risk.detect stays truthy past the timeout, the helper returns False.

    We fast-forward ``time.monotonic`` so we don't actually wait 5 min.
    """
    from csm_core.mining.platforms import douyin_search

    on_progress, _ = fake_progress
    cancel = threading.Event()

    monkeypatch.setattr(
        douyin_search._risk, "detect", lambda page, response=None: True,
    )
    monkeypatch.setattr(
        douyin_search._risk, "detect_signal",
        lambda page, response=None: type("S", (), {"layer": "text"})(),
    )
    monkeypatch.setattr(douyin_search.time, "sleep", lambda _s: None)

    # Fast-forward time so the deadline (now + 300s) elapses after a few polls.
    # Real monotonic ticks ~once per real second; here we jump 1000s per call.
    fake_clock = [0.0]
    def fast_monotonic():
        fake_clock[0] += 1000.0  # blow past the 300s timeout in one tick
        return fake_clock[0]
    monkeypatch.setattr(douyin_search.time, "monotonic", fast_monotonic)

    result = douyin_search._wait_for_captcha_cleared(
        page=None, on_progress=on_progress, cancel_event=cancel,
        emitted=5, target_count=50, platform="douyin",
    )

    assert result is False, "helper should return False when timeout elapses"


def test_platform_phase_includes_captcha_waiting():
    """v0.5.6: PlatformPhase Literal must include captcha_waiting so the
    frontend's chip logic can rely on a stable enum string."""
    import typing
    from csm_core.mining.models import PlatformPhase

    args = typing.get_args(PlatformPhase)
    assert "captcha_waiting" in args, (
        f"PlatformPhase missing captcha_waiting; current values: {args}"
    )
