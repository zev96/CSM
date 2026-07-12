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
        # Stub context.cookies returning BDUSS so _fetch_once's login pre-flight
        # check passes. These tests focus on resume/breakpoint logic, not on
        # login state — BDUSS check is exercised in test_baidu_keyword.py.
        self.context = type("_Ctx", (), {
            "cookies": lambda self, url=None: [{"name": "BDUSS", "value": "fake"}],
        })()
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


@pytest.fixture(autouse=True)
def _pin_clean_config(settings_path):
    """Pin a clean (non-native) config for every test in this file.

    Without this, ``fetch()`` calls ``config_service.load()`` which reads the
    developer's real settings.json. On a machine with native Chrome mode on
    (``use_native_chrome=True`` — the project's everyday config), ``fetch``
    passes ``use_native_chrome=`` and friends to the fake session, whose
    ``_ctx(*, headless)`` only accepts ``headless`` → TypeError before the
    code under test runs, masking the real behaviour. CI has no settings.json
    so it takes the model default (False) and never sees it — the same blind
    spot that let the brand-aliases NameError (86e9018) slip the net.

    ``settings_path`` (conftest) points config at a fresh empty tmp file →
    model defaults (use_native_chrome=False) → empty session_kwargs → the
    fake session works. Keeps local == CI. No test in this file needs native
    config, so applying it file-wide via autouse is safe.
    """
    return settings_path


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


def test_list_results_latest_is_deterministic_on_checked_at_tie(isolated_storage):
    """两条结果 checked_at 完全相同（同一时钟 tick 保存，Windows utcnow 分辨率粗）
    时，list_results / latest_result 必须返回后插入的那条（id 更大 = 真·最新），
    否则 resume 的 prior-head 读取与 KPI「最新记录」在 tie 上抖动。

    get_last_resumed_keyword 早已用 `id DESC` tiebreaker 修过同款问题；
    list_results / latest_result 必须一致，否则头尾合并读到旧断点。
    """
    task = _make_task(n_keywords=3)
    ts = datetime(2026, 7, 10, 12, 0, 0)
    storage.save_result(MonitorResult(
        task_id=task.id, checked_at=ts, status="risk_control", rank=-1,
        metric={"marker": "first"}, error_message="",
    ), alert_triggered=False)
    storage.save_result(MonitorResult(
        task_id=task.id, checked_at=ts, status="ok", rank=1,
        metric={"marker": "second"}, error_message="",
    ), alert_triggered=False)

    assert storage.list_results(task.id, limit=1)[0].metric["marker"] == "second"
    assert storage.latest_result(task.id).metric["marker"] == "second"


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
        result with last_resumed_keyword=3 (NOT 4) and publishes risk_control event.

        Off-by-one 修正：progress=kw_idx 是「命中风控、尚未抓完」的那个关键词，
        resume 必须从它本身重抓，而不是 progress+1 把它永久跳过。
        """
        from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

        signal = RiskSignal(layer="dom", detail="#captcha-mask")
        # 前 3 个关键词（kw0/kw1/kw2）已抓完，随异常带出。
        partial = [
            {"keyword": "kw0", "default_first_rank": 5, "default_matched_count": 1,
             "default_results": [], "news_results": []},
            {"keyword": "kw1", "default_first_rank": -1, "default_matched_count": 0,
             "default_results": [], "news_results": []},
            {"keyword": "kw2", "default_first_rank": 8, "default_matched_count": 1,
             "default_results": [], "news_results": []},
        ]

        class FakeAdapter:
            def fetch(self, t, **kwargs):
                raise RiskControlException(signal, progress=3, partial_keywords=partial)

        task = _make_task(n_keywords=10)

        published_events: list = []
        loop = self._make_loop(FakeAdapter(), published_events)

        result = loop._run_one(task, resume_from=0)

        # _run_one returns None for risk_control path
        assert result is None

        # Breakpoint saved: progress=3 → next_kw = 3 (re-scrape the failed kw)
        assert storage.get_last_resumed_keyword(task.id) == 3

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
        assert evt.result.metric["last_resumed_keyword"] == 3
        # New top-level fields for frontend banner
        assert risk_events[0].last_resumed_keyword == 3
        assert risk_events[0].total_keywords == 10

        # 头段数据被持久化进断点 metric.keywords（resume 拼全量的依据）
        bp_keywords = evt.result.metric["keywords"]
        assert [k["keyword"] for k in bp_keywords] == ["kw0", "kw1", "kw2"]
        # 断点聚合按头段算；total_keywords 仍是完整 N=10（进度 3/10）
        assert evt.result.metric["total_keywords"] == 10
        assert evt.result.metric["matched_keywords"] == 2
        assert evt.result.metric["best_default_first_rank"] == 5

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


def test_merge_resumed_dup_keyword_distinct_objects(monkeypatch):
    """R9：配置含重复关键词时，合并出的两个同名槽必须是**不同对象**（不共享
    引用），避免 aliasing；行数/顺序与全新扫描一致（配置里出现几次就几行）。"""
    from sidecar.csm_sidecar.services import monitor_loop as ml

    prior = MonitorResult(
        task_id=1, checked_at=datetime.utcnow(), status="risk_control", rank=-1,
        metric={"keywords": [{"keyword": "A", "default_first_rank": 5,
                              "default_matched_count": 1}]},
    )
    monkeypatch.setattr(ml.storage, "list_results", lambda tid, limit=1: [prior])
    new_rows = [
        {"keyword": "B", "default_first_rank": -1, "default_matched_count": 0},
        {"keyword": "A", "default_first_rank": 9, "default_matched_count": 1},
    ]
    merged = ml._merge_resumed_baidu_keywords(
        new_rows, resume_from=1, task_id=1, configured_keywords=["A", "B", "A"],
    )
    assert [r["keyword"] for r in merged] == ["A", "B", "A"]
    a_slots = [r for r in merged if r["keyword"] == "A"]
    assert len(a_slots) == 2
    assert a_slots[0] is not a_slots[1], "重复关键词的两个槽不能共享同一 dict 对象"


class TestRunnerResumeMerge:
    """resume 完成时头尾合并成完整快照。

    风控中断存下头段 [0..R-1]（断点 metric.keywords），resume 只抓尾段
    [R..N-1]；runner 必须把两段合并存库，否则新 ok 结果里只有尾段、
    头段永久缺失（0..R-1 显示「从未监测」）。
    """

    def _make_loop(self, fake_adapter, published_events: list):
        from sidecar.csm_sidecar.services.monitor_loop import MonitorLoop
        return MonitorLoop(
            event_sink=lambda e: published_events.append(e),
            adapters={"baidu_keyword": fake_adapter},
        )

    def test_resume_ok_merges_tail_with_prior_head(self, isolated_storage):
        task = _make_task(n_keywords=10)
        all_kw = [f"kw{i}" for i in range(10)]

        # 1. 先存断点：头段 kw0..kw2（kw0 rank5、kw2 rank8 命中）
        head = [
            {"keyword": "kw0", "default_first_rank": 5, "default_matched_count": 1,
             "default_results": [], "news_results": []},
            {"keyword": "kw1", "default_first_rank": -1, "default_matched_count": 0,
             "default_results": [], "news_results": []},
            {"keyword": "kw2", "default_first_rank": 8, "default_matched_count": 1,
             "default_results": [], "news_results": []},
        ]
        _save_result(task.id, "risk_control", {
            "last_resumed_keyword": 3, "keywords": head,
            "total_keywords": 10, "search_keywords": all_kw,
        })

        # 2. Fake adapter 返回尾段 ok 结果（仅 kw3..kw9；kw7 rank2 命中）
        tail = [
            {"keyword": f"kw{i}",
             "default_first_rank": (2 if i == 7 else -1),
             "default_matched_count": (1 if i == 7 else 0),
             "default_results": [], "news_results": []}
            for i in range(3, 10)
        ]
        tail_metric = {
            "keywords": tail, "total_keywords": 7,
            "search_keywords": [f"kw{i}" for i in range(3, 10)],
            "best_default_first_rank": 2, "matched_keywords": 1,
            "total_default_matches": 1, "target_brand": "TestBrand",
        }

        class FakeAdapter:
            def fetch(self, t, **kwargs):
                return MonitorResult(
                    task_id=t.id, checked_at=datetime.utcnow(),
                    status="ok", rank=2, metric=tail_metric,
                )

        published: list = []
        loop = self._make_loop(FakeAdapter(), published)
        result = loop._run_one(task, resume_from=3)

        assert result is not None and result.status == "ok"
        # 合并后是完整 kw0..kw9，配置顺序
        assert [k["keyword"] for k in result.metric["keywords"]] == all_kw
        assert result.metric["total_keywords"] == 10
        # 聚合按全量重算：命中 kw0/kw2/kw7 = 3；最好排名 min(5,8,2)=2
        assert result.metric["matched_keywords"] == 3
        assert result.metric["best_default_first_rank"] == 2
        assert result.rank == 2

        # 持久化的最新记录反映合并结果
        latest = storage.list_results(task.id, limit=1)[0]
        assert [k["keyword"] for k in latest.metric["keywords"]] == all_kw
        # ok 结果绝不能带断点标记，否则下次 resume 会误触发
        assert "last_resumed_keyword" not in latest.metric

    def test_resume_failure_keeps_breakpoint_intact(self, isolated_storage):
        """resume 返回 failed（尾段全失败 / 坏副本，成因常与断点同源）时，绝不能
        用失败结果覆盖断点 —— 否则保全的头段从最新快照消失、last_resumed_keyword
        丢失导致下次从 0 全扫。断点保留、发 failed 事件让用户可重试续抓。"""
        task = _make_task(n_keywords=10)
        all_kw = [f"kw{i}" for i in range(10)]
        head = [
            {"keyword": "kw0", "default_first_rank": 5, "default_matched_count": 1,
             "default_results": [], "news_results": []},
            {"keyword": "kw1", "default_first_rank": -1, "default_matched_count": 0,
             "default_results": [], "news_results": []},
            {"keyword": "kw2", "default_first_rank": 8, "default_matched_count": 1,
             "default_results": [], "news_results": []},
        ]
        _save_result(task.id, "risk_control", {
            "last_resumed_keyword": 3, "keywords": head,
            "total_keywords": 10, "search_keywords": all_kw,
        })

        # resume 尾段全失败 → 适配器返回 status="failed"
        class FakeAdapter:
            def fetch(self, t, **kwargs):
                return MonitorResult(
                    task_id=t.id, checked_at=datetime.utcnow(), status="failed",
                    rank=-1, metric={"keywords": [], "total_keywords": 7},
                    error_message="全部 7 个关键词抓取失败：断网",
                )

        published: list = []
        loop = self._make_loop(FakeAdapter(), published)
        result = loop._run_one(task, resume_from=3)

        # 不落库失败结果 → 断点仍是最新，头段 + 断点位置都在
        latest = storage.list_results(task.id, limit=1)[0]
        assert latest.status == "risk_control"
        assert [k["keyword"] for k in latest.metric["keywords"]] == ["kw0", "kw1", "kw2"]
        assert storage.get_last_resumed_keyword(task.id) == 3
        # 发了 failed 事件让用户知道续抓失败
        assert any(e.kind == "failed" for e in published)


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

            def is_task_active(self, task_id):
                # resume 只在任务已暂停（非 active）时用；固定 False。
                return False

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
