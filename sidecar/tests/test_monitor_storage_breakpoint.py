"""Tests for Task 4: storage breakpoint helpers + adapter resume_from support.

Tests cover:
1. get_last_resumed_keyword reads last_resumed_keyword from latest result's
   metric_json when present.
2. get_last_resumed_keyword returns None when the key is absent.
3. BaiduKeywordAdapter.fetch(task, resume_from=N) skips the first N keywords.
4. End-to-end: prior risk_control result → get_last_resumed_keyword → adapter
   visits only the remaining keywords.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.platforms import baidu_keyword


# ── Shared fake helpers ───────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, *, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/html; charset=utf-8"}


class _TrackingSession:
    """Fake incognito session that records which SERP URLs were visited."""

    def __init__(self, *, visited: list[str]):
        self._visited = visited
        self._current_url = ""
        self.page = self
        self.context = None
        self.browser = None
        self.pw = None

    def goto(self, url, **kw):
        self._current_url = url
        if "baidu.com/s?" in url:
            qs = parse_qs(urlparse(url).query)
            self._visited.append(qs.get("wd", [""])[0])

    @property
    def url(self):
        return self._current_url

    def content(self):
        # Return a minimal SERP HTML so parse_serp works (returns empty links)
        return "<html><body></body></html>"

    def locator(self, sel):
        class _NullLocator:
            def count(self):
                return 0
        return _NullLocator()


# ── Storage isolation fixture ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Give each test its own fresh DB file so tests are fully independent."""
    db_path = tmp_path / "test_monitor.db"
    monkeypatch.setattr(storage, "_db_path", None)
    monkeypatch.setattr(storage, "_initialized", False)
    monkeypatch.setattr(storage, "_local", storage.threading.local())
    storage.init_db(db_path)
    yield
    conn = getattr(storage._local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        storage._local.conn = None


@pytest.fixture
def no_wait_pacer(monkeypatch):
    """Make rate-limit pacer.wait() a no-op so tests don't sleep."""
    from csm_core.monitor import rate_limit as _rl

    class _NoWaitPacer:
        def wait(self):
            pass
        def configure(self, **kw):
            pass

    monkeypatch.setattr(_rl, "get_pacer", lambda name: _NoWaitPacer())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_task(*, n_keywords: int = 10) -> MonitorTask:
    task = MonitorTask(
        type="baidu_keyword",
        name="breakpoint-test",
        target_url="https://www.baidu.com/s?wd=kw0",
        config={
            "search_keywords": [f"kw{i}" for i in range(n_keywords)],
            "target_brand": "TestBrand",
        },
    )
    task_id = storage.create_task(task)
    task.id = task_id
    return task


def _save_result(task_id: int, status: str, metric: dict) -> None:
    result = MonitorResult(
        task_id=task_id,
        checked_at=datetime.utcnow(),
        status=status,
        rank=-1,
        metric=metric,
        error_message="",
    )
    storage.save_result(result, alert_triggered=False)


def _make_fake_session_ctx(visited: list[str]):
    """Return a context manager factory that yields a _TrackingSession."""
    @contextmanager
    def _ctx(*, headless: bool):
        yield _TrackingSession(visited=visited)
    return _ctx


# ── Storage helper tests ──────────────────────────────────────────────────────

def test_get_last_resumed_keyword_reads_from_metric():
    """save_result with last_resumed_keyword=5 → get_last_resumed_keyword returns 5."""
    task = _make_task()
    _save_result(task.id, "risk_control", {"last_resumed_keyword": 5, "keywords": []})
    assert storage.get_last_resumed_keyword(task.id) == 5


def test_get_last_resumed_keyword_returns_none_when_no_results():
    """Task with no results → None."""
    task = _make_task()
    assert storage.get_last_resumed_keyword(task.id) is None


def test_get_last_resumed_keyword_returns_none_when_key_absent_in_metric():
    """Result exists but metric has no last_resumed_keyword key → None."""
    task = _make_task()
    _save_result(task.id, "ok", {"keywords": []})
    assert storage.get_last_resumed_keyword(task.id) is None


def test_get_last_resumed_keyword_reads_latest_result():
    """Multiple results: function reads the most recent one."""
    task = _make_task()
    _save_result(task.id, "risk_control", {"last_resumed_keyword": 3})
    _save_result(task.id, "risk_control", {"last_resumed_keyword": 7})
    assert storage.get_last_resumed_keyword(task.id) == 7


def test_get_last_resumed_keyword_returns_zero():
    """last_resumed_keyword=0 is valid and must not be treated as falsy."""
    task = _make_task()
    _save_result(task.id, "risk_control", {"last_resumed_keyword": 0})
    assert storage.get_last_resumed_keyword(task.id) == 0


# ── Adapter resume_from tests ─────────────────────────────────────────────────

def test_fetch_with_resume_from_skips_initial_keywords(monkeypatch, no_wait_pacer):
    """resume_from=3 causes adapter to visit only kw3-kw9 (7 keywords)."""
    visited: list[str] = []
    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", _make_fake_session_ctx(visited))
    monkeypatch.setattr(baidu_keyword, "detect_risk", lambda page, response=None: None)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp())

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="resume-test",
        target_url="https://www.baidu.com/s?wd=kw0",
        config={
            "search_keywords": [f"kw{i}" for i in range(10)],
            "target_brand": "TestBrand",
        },
    )

    result = baidu_keyword.ADAPTER.fetch(task, resume_from=3)

    assert result.status == "ok", f"unexpected status {result.status!r}: {result.error_message}"
    assert visited == [f"kw{i}" for i in range(3, 10)], (
        f"expected kw3-kw9 but got: {visited}"
    )
    # total_keywords reflects the full configured list (10), not the resumed slice
    assert result.metric["total_keywords"] == 10
    # keywords list only contains entries for visited keywords (7)
    assert len(result.metric["keywords"]) == 7


def test_fetch_resume_from_zero_visits_all_keywords(monkeypatch, no_wait_pacer):
    """resume_from=0 (default) visits every configured keyword."""
    visited: list[str] = []
    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", _make_fake_session_ctx(visited))
    monkeypatch.setattr(baidu_keyword, "detect_risk", lambda page, response=None: None)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp())

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="full-test",
        target_url="https://www.baidu.com/s?wd=kw0",
        config={
            "search_keywords": [f"kw{i}" for i in range(5)],
            "target_brand": "TestBrand",
        },
    )

    result = baidu_keyword.ADAPTER.fetch(task, resume_from=0)
    assert result.status == "ok"
    assert visited == [f"kw{i}" for i in range(5)]


def test_fetch_risk_exception_has_absolute_progress_after_resume(monkeypatch, no_wait_pacer):
    """When resume_from=5 and risk hits at relative index 2, progress should be 7 (absolute)."""
    from csm_core.monitor.drivers.risk_detector import RiskControlException, RiskSignal

    call_count = {"n": 0}

    def fake_detect_risk(page, response=None):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            return RiskSignal(layer="dom", detail="DOM matched '#captcha-mask'")
        return None

    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", _make_fake_session_ctx([]))
    monkeypatch.setattr(baidu_keyword, "detect_risk", fake_detect_risk)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp())

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="progress-test",
        target_url="https://www.baidu.com/s?wd=kw0",
        config={
            "search_keywords": [f"kw{i}" for i in range(10)],
            "target_brand": "TestBrand",
        },
    )

    with pytest.raises(RiskControlException) as exc_info:
        baidu_keyword.ADAPTER.fetch(task, resume_from=5)

    # resume_from=5, risk at relative_idx=2 → absolute index = 5+2 = 7
    assert exc_info.value.progress == 7, (
        f"expected absolute progress=7, got {exc_info.value.progress}"
    )


# ── End-to-end breakpoint integration test ───────────────────────────────────

def test_resume_from_breakpoint_uses_stored_position(monkeypatch, no_wait_pacer):
    """Prior risk_control result with last_resumed_keyword=3 → adapter skips kw0-kw2."""
    task = _make_task(n_keywords=10)
    _save_result(task.id, "risk_control", {"last_resumed_keyword": 3})

    # Verify storage
    assert storage.get_last_resumed_keyword(task.id) == 3

    visited: list[str] = []
    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", _make_fake_session_ctx(visited))
    monkeypatch.setattr(baidu_keyword, "detect_risk", lambda page, response=None: None)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp())

    resume_from = storage.get_last_resumed_keyword(task.id) or 0
    assert resume_from == 3

    result = baidu_keyword.ADAPTER.fetch(task, resume_from=resume_from)

    assert result.status == "ok"
    assert visited == [f"kw{i}" for i in range(3, 10)], (
        f"expected kw3-kw9, got: {visited}"
    )


def test_resume_from_greater_than_keyword_count_yields_empty_scan(monkeypatch, no_wait_pacer):
    """resume_from >= len(keywords) → adapter clamps, scan visits nothing, status='ok'."""
    visited: list[str] = []
    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", _make_fake_session_ctx(visited))
    monkeypatch.setattr(baidu_keyword, "detect_risk", lambda page, response=None: None)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp())

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="clamp-test",
        target_url="https://www.baidu.com/s?wd=kw0",
        config={
            "search_keywords": [f"kw{i}" for i in range(5)],
            "target_brand": "TestBrand",
        },
    )

    # resume_from=10 is well past the 5 keywords
    result = baidu_keyword.ADAPTER.fetch(task, resume_from=10)

    assert result.status == "ok", f"unexpected status: {result.status!r}: {result.error_message}"
    assert visited == [], f"expected no keywords visited, got: {visited}"


# ── MonitorLoop runner _RiskControlException handler tests ───────────────────


class TestRunnerRiskControlHandler:
    """Tests for MonitorLoop._run_one's _RiskControlException catch path.

    The handler saves a risk_control MonitorResult with last_resumed_keyword,
    and publishes a MonitorEvent. These are the highest-risk new code paths
    in this PR — exception ordering matters, dispatch order matters.

    MonitorLoop accepts an ``adapters`` dict at construction so we can inject
    a fake adapter without any monkeypatching of the module-level registry.
    """

    def _make_loop(self, fake_adapter, published_events: list) -> "MonitorLoop":
        from sidecar.csm_sidecar.services.monitor_loop import MonitorLoop
        loop = MonitorLoop(
            event_sink=lambda e: published_events.append(e),
            adapters={"baidu_keyword": fake_adapter},
        )
        return loop

    def test_handler_saves_breakpoint_and_publishes_event(self, isolated_storage):
        """Fake adapter raises RiskControlException(progress=3) → handler saves
        result with last_resumed_keyword=4 and publishes risk_control event."""
        from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

        signal = RiskSignal(layer="dom", detail="#captcha-mask")

        class FakeAdapter:
            def fetch(self, t, **kwargs):
                raise RiskControlException(signal, progress=3)

        task = _make_task(n_keywords=10)

        published_events: list = []
        loop = self._make_loop(FakeAdapter(), published_events)

        result = loop._run_one(task, resume_from=0)

        # _run_one returns None for risk_control path
        assert result is None

        # Breakpoint saved: progress=3 → next_kw = 3+1 = 4
        assert storage.get_last_resumed_keyword(task.id) == 4

        # risk_control event published (after started event)
        risk_events = [e for e in published_events if e.kind == "risk_control"]
        assert len(risk_events) == 1
        evt = risk_events[0]
        assert evt.task_id == task.id
        # error field should reference the signal layer
        assert "dom" in (evt.error or "")
        # result field carries the breakpoint MonitorResult
        assert evt.result is not None
        assert evt.result.status == "risk_control"
        assert evt.result.metric["last_resumed_keyword"] == 4
        # New top-level fields for frontend banner
        assert risk_events[0].last_resumed_keyword == 4
        assert risk_events[0].total_keywords == 10

    def test_handler_none_progress_resumes_from_zero(self, isolated_storage):
        """RiskControlException(progress=None) — non-positional risk —
        last_resumed_keyword should be 0 (fresh full re-scan on resume)."""
        from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

        signal = RiskSignal(layer="text", detail="网络异常")

        class FakeAdapter:
            def fetch(self, t, **kwargs):
                raise RiskControlException(signal, progress=None)

        task = _make_task(n_keywords=5)

        published_events: list = []
        loop = self._make_loop(FakeAdapter(), published_events)

        result = loop._run_one(task, resume_from=0)

        assert result is None

        # progress=None → next_kw = 0 → fresh full re-scan on resume
        assert storage.get_last_resumed_keyword(task.id) == 0

        risk_events = [e for e in published_events if e.kind == "risk_control"]
        assert len(risk_events) == 1


# ── POST /api/monitor/tasks/{task_id}/resume route tests ─────────────────────


class TestResumeRoute:
    """POST /api/monitor/tasks/{task_id}/resume tests.

    Routes are protected by RequireToken. We bypass auth by patching the
    auth._TOKEN to a known value and passing it as a Bearer header.
    monitor_lifecycle.get() is patched to return a fake loop so we don't
    need a real running APScheduler.
    """

    @pytest.fixture(autouse=True)
    def setup_auth_and_storage(self, monkeypatch):
        """Patch auth token + ensure storage is available (isolated_storage handles DB)."""
        from sidecar.csm_sidecar import auth
        monkeypatch.setattr(auth, "_TOKEN", "test-token")

    @pytest.fixture
    def client(self, setup_auth_and_storage):
        from fastapi.testclient import TestClient
        from sidecar.csm_sidecar.main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    def _patch_loop(self, monkeypatch, captured: dict, *, is_running: bool = True):
        """Inject a fake MonitorLoop into monitor_lifecycle."""
        from sidecar.csm_sidecar.services import monitor_lifecycle

        class FakeLoop:
            def is_running(self):
                return is_running

            def run_task_now(self, task_id, *, resume_from=0, keyword_override=None):
                captured["task_id"] = task_id
                captured["resume_from"] = resume_from
                return None

        monkeypatch.setattr(monitor_lifecycle, "_loop", FakeLoop())

    def test_resume_route_reads_breakpoint_and_dispatches(
        self, client, auth_headers, monkeypatch, isolated_storage
    ):
        """Task with stored last_resumed_keyword=3 → POST resume → dispatches with resume_from=3."""
        task = _make_task(n_keywords=10)
        _save_result(task.id, "risk_control", {"last_resumed_keyword": 3})

        captured: dict = {}
        self._patch_loop(monkeypatch, captured)

        response = client.post(
            f"/api/monitor/tasks/{task.id}/resume", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task.id
        assert data["resume_from"] == 3
        assert captured.get("resume_from") == 3

    def test_resume_route_404_on_missing_task(self, client, auth_headers, monkeypatch):
        """Non-existent task_id → 404."""
        captured: dict = {}
        self._patch_loop(monkeypatch, captured)

        response = client.post(
            "/api/monitor/tasks/999999/resume", headers=auth_headers
        )
        assert response.status_code == 404

    def test_resume_route_defaults_to_zero_when_no_breakpoint(
        self, client, auth_headers, monkeypatch, isolated_storage
    ):
        """Task with no risk_control result → resume_from=0 (equivalent to run-now)."""
        task = _make_task(n_keywords=5)
        # No risk_control result saved — task has a clean history

        captured: dict = {}
        self._patch_loop(monkeypatch, captured)

        response = client.post(
            f"/api/monitor/tasks/{task.id}/resume", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task.id
        assert data["resume_from"] == 0
        assert captured.get("resume_from") == 0
