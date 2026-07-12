from __future__ import annotations
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.geo.models import GeoAnswer, Citation
from csm_core.monitor.platforms import geo_query as geo_mod


@pytest.fixture
def fresh_db(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


class FakeProvider:
    def __init__(self, platform):
        self.platform = platform
        self.mode = "api"

    def query(self, keyword, *, web_search=True, cancel_token=None):
        return GeoAnswer(platform=self.platform, keyword=keyword,
                         answer_text=f"{self.platform} 推荐 小鹏 G6",
                         citations=[Citation(url="https://zhuanlan.zhihu.com/p/1", title="知乎")])


class FakeClient:
    def complete(self, *, system, user, temperature=None):
        return '{"mentioned":true,"target_rank":1,"sentiment":"pos","recommended":[{"name":"小鹏","position":1}],"summary":"正面"}'


def test_fetch_fans_out_and_records(fresh_db, monkeypatch):
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: FakeProvider(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="小鹏卡位", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["新能源SUV", "智驾车"],
                "platforms": ["tongyi", "kimi"], "extract_provider": "mock"}))
    task = storage.get_task(tid)

    progress = []
    result = geo_mod.ADAPTER.fetch(task, progress_cb=lambda c, t: progress.append((c, t)))

    assert result.status == "ok"
    assert result.rank == 1                      # 全 rank==1 → 中位 1
    assert result.metric["soc"] == 1.0
    assert result.metric["first_rank_rate"] == 1.0
    assert result.metric["error_cells"] == 0     # 全 ok，没有采集失败
    assert result.metric["partial_resume"] is False
    assert progress[0] == (0, 4)                 # 初始 0/total 事件（先于第一个 cell）
    assert progress[-1] == (4, 4)                # 2 关键词 × 2 平台

    # ── Simulate monitor_loop._run_one: the LOOP persists the result, the
    # adapter must NOT. This is the C1 regression guard — if the adapter
    # ever calls save_result again, this run yields 2 monitor_results rows.
    from csm_core.monitor.geo import storage as geo_storage
    storage.save_result(result)
    conn = storage.get_conn()
    assert conn.execute(
        "SELECT count(*) FROM monitor_results WHERE task_id=?", (tid,)
    ).fetchone()[0] == 1                          # 单写：loop 存一行，adapter 不自存

    # geo 明细落库 + 下钻按 (task_id, checked_at) 关联回这 4 个 cell。
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 4
    drill = geo_storage.cells_for_run(tid, result.checked_at)
    assert len(drill) == 4


def test_all_cells_failed_marks_run_failed(fresh_db, monkeypatch):
    # I1: when BOTH platforms raise, every cell is error → the run must be
    # status="failed" (not ok+rank=-1), so notify.should_alert returns False
    # and the user doesn't get a false "排名跌出 Top-N" alert.
    class Boom(FakeProvider):
        def query(self, *a, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: Boom(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["k1", "k2"], "platforms": ["tongyi", "kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))

    assert result.status == "failed"             # 全失败 → failed
    assert result.rank == -1
    assert result.metric["error_cells"] == 4     # 2 关键词 × 2 平台，全错
    assert result.error_message                  # 带首个失败 cell 的错误摘要

    # cells 仍然落库（数据不丢），且下钻能取回。
    from csm_core.monitor.geo import storage as geo_storage
    drill = geo_storage.cells_for_run(tid, result.checked_at)
    assert len(drill) == 4
    assert all(c["status"] == "error" for c in drill)


def test_one_provider_error_does_not_kill_run(fresh_db, monkeypatch):
    def picker(p):
        if p == "kimi":
            class Boom(FakeProvider):
                def query(self, *a, **k):
                    raise RuntimeError("boom")
            return Boom(p)
        return FakeProvider(p)
    monkeypatch.setattr(geo_mod, "get_provider", picker)
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                 # 部分失败不整体失败
    assert result.metric["error_cells"] == 1     # 仅 kimi 失败 → I2 surface
    conn = storage.get_conn()
    rows = conn.execute("SELECT platform, status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()
    statuses = {r["platform"]: r["status"] for r in rows}
    assert statuses["tongyi"] == "ok"
    assert statuses["kimi"] == "error"


class NotMentionedClient:
    def complete(self, *, system, user, temperature=None):
        return '{"mentioned":false,"target_rank":-1,"sentiment":"na","recommended":[],"summary":""}'


def test_fetch_writes_geo_alerts_into_metric(fresh_db, monkeypatch):
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: FakeProvider(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: NotMentionedClient())
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://b",
        config={"brand": "小鹏", "keywords": ["k"], "platforms": ["tongyi"], "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                       # provider succeeded → cell ok
    assert any(a["kind"] == "hidden" for a in result.metric.get("alerts", []))


def test_run_cell_passes_cancel_token_to_provider(monkeypatch):
    import threading
    from csm_core.monitor.platforms import geo_query as gq

    seen = {}

    class _Prov:
        platform = "deepseek"; mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            seen["cancel_token"] = cancel_token
            from csm_core.monitor.geo.models import GeoAnswer
            return GeoAnswer(platform="deepseek", keyword=kw, answer_text="x", status="ok")

    monkeypatch.setattr(gq, "get_provider", lambda p: _Prov())
    monkeypatch.setattr(gq, "extract",
                        lambda ans, **k: __import__("csm_core.monitor.geo.models", fromlist=["GeoExtraction"]).GeoExtraction())
    tok = threading.Event()
    adapter = gq.GeoQueryAdapter()
    adapter._run_cell("kw", "deepseek", "Brand", [], True, object(), cancel_token=tok)
    assert seen["cancel_token"] is tok


def test_geo_query_configures_serial_concurrency():
    # 模块导入即把 geo_query 并发设为 1（slot 在 loop 里先于 fetch 获取）
    from csm_core.browser_infra import rate_limit
    from csm_core.monitor.platforms import geo_query  # noqa: F401  确保已导入
    assert rate_limit._max_concurrent.get("geo_query") == 1


def test_is_cancelled_helper():
    import pytest
    from csm_core.monitor.base import is_cancelled
    assert is_cancelled(ValueError("x")) is False
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        pytest.skip("sidecar 不可用")
    assert is_cancelled(_CancelledFetch("c")) is True


def test_run_cell_reraises_cancellation(monkeypatch):
    import pytest
    from csm_core.monitor.platforms import geo_query as gq
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        pytest.skip("sidecar 不可用")

    class _CancelProv:
        platform = "deepseek"; mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            raise _CancelledFetch("cancelled by user")

    monkeypatch.setattr(gq, "get_provider", lambda p: _CancelProv())
    with pytest.raises(_CancelledFetch):
        gq.GeoQueryAdapter()._run_cell("kw", "deepseek", "B", [], True, object())


def test_run_cell_normal_exception_still_becomes_error_cell(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq

    class _BoomProv:
        platform = "deepseek"; mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            raise ValueError("boom")

    monkeypatch.setattr(gq, "get_provider", lambda p: _BoomProv())
    cell = gq.GeoQueryAdapter()._run_cell("kw", "deepseek", "B", [], True, object())
    assert cell.status == "error"


def test_fetch_uses_dual_lane_api_concurrent(fresh_db, monkeypatch):
    import threading as _t
    barrier = _t.Barrier(2, timeout=3)

    class _ApiProv:
        def __init__(self, p):
            self.platform = p; self.mode = "api"
        def query(self, keyword, *, web_search=True, cancel_token=None):
            barrier.wait()                       # 两 API cell 必须并发才通过
            from csm_core.monitor.geo.models import GeoAnswer
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             answer_text=f"{self.platform} 推荐 小鹏")

    monkeypatch.setattr(geo_mod, "get_provider", lambda p: _ApiProv(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "doubao"],
                "extract_provider": "mock", "geo_api_pool_size": 2}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                 # 未 BrokenBarrier → 两 API cell 并发成功
    assert result.metric["error_cells"] == 0


def test_fetch_isolates_unconstructable_platform(fresh_db, monkeypatch):
    # I1 回归守卫:某平台 get_provider 抛错(未知/废弃平台 key、模块 import 失败)
    # 必须只让该平台变 error cell,健康平台照常成功;整轮不因分类阶段异常而崩。
    from csm_core.monitor.geo.providers.base import GeoProviderError

    def picker(p):
        if p == "badplat":
            raise GeoProviderError("未知 GEO 平台: badplat")
        return FakeProvider(p)
    monkeypatch.setattr(geo_mod, "get_provider", picker)
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "badplat"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                  # 一个坏平台不拖垮整轮
    assert result.metric["error_cells"] == 1
    conn = storage.get_conn()
    rows = conn.execute("SELECT platform, status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()
    statuses = {r["platform"]: r["status"] for r in rows}
    assert statuses["tongyi"] == "ok"
    assert statuses["badplat"] == "error"


def test_fetch_cancel_midrun_not_swallowed_as_ok(fresh_db, monkeypatch):
    # C1 回归守卫:cell 过了起始检查点后用户 Stop(token 置位),同步 POST 无法中途察觉 →
    # cell 返回 ok。fetch 必须在 runner 返回后复查 token,把「运行期间被取消」抛成取消,
    # 而不是悄悄 status=ok。
    import threading as _t
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        pytest.skip("sidecar 不可用,无法区分取消")
    tok = _t.Event()

    class _StopMidProv:
        def __init__(self, p):
            self.platform = p; self.mode = "api"
        def query(self, kw, *, web_search=True, cancel_token=None):
            from csm_core.monitor.geo.models import GeoAnswer
            tok.set()                          # 模拟用户在本 cell 执行期间点 Stop
            return GeoAnswer(platform=self.platform, keyword=kw, answer_text="x 推荐 小鹏 G6")

    monkeypatch.setattr(geo_mod, "get_provider", lambda p: _StopMidProv(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi"], "extract_provider": "mock"}))
    with pytest.raises(_CancelledFetch):
        geo_mod.ADAPTER.fetch(storage.get_task(tid), cancel_token=tok)


def test_fetch_rpa_lane_reuses_session_per_platform(fresh_db, monkeypatch):
    # RPA 平台每平台只开一次 session，循环关键词；一个坏关键词只坏一个 cell，不拖垮整轮。
    import contextlib
    opens = {"n": 0}

    class _RpaProv:
        def __init__(self, p): self.platform = p; self.mode = "rpa"
        @contextlib.contextmanager
        def session(self, *, web_search=True, cancel_token=None, retry=1):
            opens["n"] += 1
            from csm_core.monitor.geo.models import GeoAnswer
            def query_one(kw):
                if kw == "bad":
                    raise RuntimeError("selector drift")
                return GeoAnswer(platform=self.platform, keyword=kw, answer_text=f"{kw} 推荐 小鹏")
            yield query_one

    monkeypatch.setattr(geo_mod, "get_provider", lambda p: _RpaProv(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1", "bad", "k2"], "platforms": ["kimi"],
                "extract_provider": "mock",
                "geo_rpa_jitter_min": 0, "geo_rpa_jitter_max": 0}))   # 单测关 jitter,别真睡
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))

    assert opens["n"] == 1                        # kimi 只开一次 session(3 关键词复用)
    assert result.status == "ok"                  # 部分失败不整体失败
    assert result.metric["error_cells"] == 1      # 仅 "bad" 关键词失败
    conn = storage.get_conn()
    rows = {r["keyword"]: r["status"] for r in
            conn.execute("SELECT keyword,status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()}
    assert rows == {"k1": "ok", "bad": "error", "k2": "ok"}


def test_fetch_tolerates_non_numeric_pool_config(fresh_db, monkeypatch):
    # 非数值 geo_api_pool_size 不应崩 fetch,应回落默认。
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: FakeProvider(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi"],
                "extract_provider": "mock", "geo_api_pool_size": "abc"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"


def test_fetch_rpa_session_open_failure_isolates_platform(fresh_db, monkeypatch):
    # RPA session 开启失败(浏览器起不来)→ 该平台每关键词各出 error cell、只尝试开一次,
    # cell 数目对齐(runner 漏产守卫不触发);单平台全 error → 全失败保护标 failed。
    import contextlib

    opens = {"n": 0}

    class _BadSession:
        def __init__(self, p):
            self.platform = p
            self.mode = "rpa"

        @contextlib.contextmanager
        def session(self, *, web_search=True, cancel_token=None, retry=1):
            opens["n"] += 1
            raise RuntimeError("browser launch failed")
            yield  # pragma: no cover

    monkeypatch.setattr(geo_mod, "get_provider", lambda p: _BadSession(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1", "k2"], "platforms": ["kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert opens["n"] == 1                        # 只尝试开一次 session(不是每关键词各开)
    assert result.status == "failed"             # 单平台全 error → 全失败保护
    conn = storage.get_conn()
    rows = {r["keyword"]: r["status"] for r in
            conn.execute("SELECT keyword,status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()}
    assert rows == {"k1": "error", "k2": "error"}


def test_run_cell_populates_fail_reason(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    from csm_core.monitor.geo.models import GeoAnswer

    adapter = gq.GeoQueryAdapter()

    # blocked(未登录)→ fail_reason=not_logged_in
    class _Blocked:
        mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            return GeoAnswer(platform="deepseek", keyword=kw, status="blocked",
                             error="DeepSeek 未登录，请在设置中登录")
    monkeypatch.setattr(gq, "get_provider", lambda p: _Blocked())
    cell = adapter._run_cell("k1", "deepseek", "云野", [], True, client=object())
    assert cell.status == "blocked"
    assert cell.fail_reason == "not_logged_in"

    # 异常(流超时)→ status=error, fail_reason=timeout
    class _Timeout:
        mode = "rpa"
        def query(self, kw, *, web_search, cancel_token=None):
            raise TimeoutError("wait_stream_done exceeded 180s")
    monkeypatch.setattr(gq, "get_provider", lambda p: _Timeout())
    cell = adapter._run_cell("k1", "kimi", "云野", [], True, client=object())
    assert cell.status == "error"
    assert cell.fail_reason == "timeout"


def test_run_cell_on_session_populates_fail_reason():
    from csm_core.monitor.platforms import geo_query as gq
    from csm_core.monitor.geo.models import GeoAnswer

    adapter = gq.GeoQueryAdapter()

    def query_one(kw):   # 直接给 session 上的 query_one
        return GeoAnswer(platform="yuanbao", keyword=kw, status="blocked",
                         error="腾讯元宝 未登录，请在设置中扫码登录")
    cell = adapter._run_cell_on_session(query_one, "k1", "yuanbao", "云野", [], client=object())
    assert cell.status == "blocked"
    assert cell.fail_reason == "not_logged_in"


def _fake_provider_yielding(script):
    """返回一个 provider,其 session() 的 query_one(kw) 按 script[kw] 出 GeoAnswer。"""
    import contextlib
    from csm_core.monitor.geo.models import GeoAnswer

    class _P:
        mode = "rpa"
        @contextlib.contextmanager
        def session(self, *, web_search, cancel_token=None, retry=1):
            def query_one(kw):
                st, err = script[kw]
                if st == "ok":
                    return GeoAnswer(platform="kimi", keyword=kw, answer_text="有内容", status="ok")
                return GeoAnswer(platform="kimi", keyword=kw, status=st, error=err)
            yield query_one
    return _P()


def _drain_batch(adapter, plat, kws, provider, monkeypatch, consec_skip=3):
    from csm_core.monitor.platforms import geo_query as gq
    monkeypatch.setattr(gq, "get_provider", lambda p: provider)
    # ok cell 会走 extract → 打桩成恒定 GeoExtraction,避免真调 LLM。
    from csm_core.monitor.geo.models import GeoExtraction
    monkeypatch.setattr(gq, "extract",
                        lambda answer, *, brand, aliases, client: GeoExtraction(mentioned=False))
    out = list(adapter._rpa_batch(plat, kws, None, web_search=True, brand="云野",
                                  aliases=[], client=object(), consec_skip=consec_skip))
    return out


def test_rpa_batch_login_gate_synthesizes_rest(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3"]
    provider = _fake_provider_yielding({
        "k1": ("blocked", "Kimi 未登录，请在设置中登录"),
        "k2": ("ok", ""), "k3": ("ok", ""),   # 不该被调用
    })
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch)
    assert [li for li, _ in out] == [0, 1, 2]              # 契约:每关键词一 cell
    cells = [c for _, c in out]
    assert cells[0].status == "blocked" and cells[0].fail_reason == "not_logged_in"
    for c in cells[1:]:                                    # k2/k3 合成:blocked + 继承 + synthetic
        assert c.status == "blocked"
        assert c.fail_reason == "not_logged_in"
        assert c.raw.get("synthetic") is True


def test_rpa_batch_interrupt_does_not_feed_consecutive_skip(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3", "k4"]
    # 连续 interrupted(睡眠唤醒)error → 不喂连败计数 → 不短路,逐个照跑到底(即便 consec_skip=2)
    provider = _fake_provider_yielding({k: ("error", "睡眠唤醒 interrupted") for k in kws})
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch, consec_skip=2)
    assert [li for li, _ in out] == [0, 1, 2, 3]                 # 四个都真跑,无短路
    cells = [c for _, c in out]
    assert all(c.fail_reason == "interrupted" for c in cells)
    assert not any(c.raw.get("synthetic") for c in cells)        # 未产合成 cell


def test_sleep_jitter_waits_random_delay_and_is_cancelable():
    from csm_core.monitor.platforms import geo_query as gq
    import threading
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        _CancelledFetch = RuntimeError
    calls = {}
    tok = threading.Event()
    def _fake_wait(d):
        calls["delay"] = d
        return False                        # 未取消 → 睡满
    tok.wait = _fake_wait                    # type: ignore[method-assign]
    gq._sleep_jitter(tok, 10, 20, _rand=lambda a, b: 12.5)
    assert calls["delay"] == 12.5           # 把 random.uniform 的值交给 Event.wait

    tok2 = threading.Event(); tok2.set()     # 已取消 → wait 立刻 True → maybe_cancel 抛
    import pytest
    with pytest.raises(_CancelledFetch):
        gq._sleep_jitter(tok2, 10, 20, _rand=lambda a, b: 1.0)


def test_sleep_jitter_zero_max_is_noop():
    from csm_core.monitor.platforms import geo_query as gq
    gq._sleep_jitter(None, 0, 0)            # hi<=0 → 直接返回,不睡不抛(禁用 jitter)


def test_rpa_batch_consecutive_fail_short_circuits(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3", "k4", "k5"]
    provider = _fake_provider_yielding({
        "k1": ("error", "wait_stream_done exceeded"),
        "k2": ("error", "wait_stream_done exceeded"),
        "k3": ("error", "wait_stream_done exceeded"),
        "k4": ("ok", ""), "k5": ("ok", ""),   # 不该被调用
    })
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch, consec_skip=3)
    cells = [c for _, c in out]
    assert len(cells) == 5                                 # 契约:补足 5 个
    assert [c.status for c in cells[:3]] == ["error", "error", "error"]
    assert all(c.fail_reason == "timeout" for c in cells[:3])
    for c in cells[3:]:                                    # k4/k5 合成,继承 timeout
        assert c.status == "blocked"
        assert c.fail_reason == "timeout"
        assert c.raw.get("synthetic") is True


def test_rpa_batch_no_early_skip_when_recovers(monkeypatch):
    from csm_core.monitor.platforms import geo_query as gq
    adapter = gq.GeoQueryAdapter()
    kws = ["k1", "k2", "k3", "k4"]
    # error,error,ok(连败清零),error → 从不达 3 连败,全部真跑,无合成
    provider = _fake_provider_yielding({
        "k1": ("error", "x"), "k2": ("error", "x"),
        "k3": ("ok", ""), "k4": ("error", "x"),
    })
    out = _drain_batch(adapter, "kimi", kws, provider, monkeypatch, consec_skip=3)
    cells = [c for _, c in out]
    assert [c.raw.get("synthetic") for c in cells] == [None, None, None, None]
    assert [c.status for c in cells] == ["error", "error", "ok", "error"]


def test_rpa_batch_cancellation_mid_loop_propagates(monkeypatch):
    # 锁定:_rpa_batch 循环内(第 2 个关键词起)token 置位 → maybe_cancel 抛取消,必须
    # 原样上抛给 runner/loop,绝不被 except 吞成合成/error cell。首格 ok 先产出,取消发生在
    # 第 2 次 maybe_cancel(tok),此后不再产出任何 cell。
    import contextlib
    import threading as _t
    from csm_core.monitor.platforms import geo_query as gq
    from csm_core.monitor.geo.models import GeoAnswer, GeoExtraction
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        pytest.skip("sidecar 不可用,无法区分取消")

    tok = _t.Event()

    class _StopMidProv:
        mode = "rpa"
        @contextlib.contextmanager
        def session(self, *, web_search, cancel_token=None, retry=1):
            def query_one(kw):
                if kw == "k1":
                    tok.set()          # 模拟用户在第 1 个关键词执行期间点 Stop
                return GeoAnswer(platform="kimi", keyword=kw, answer_text="有内容", status="ok")
            yield query_one

    monkeypatch.setattr(gq, "get_provider", lambda p: _StopMidProv())
    monkeypatch.setattr(gq, "extract",
                        lambda answer, *, brand, aliases, client: GeoExtraction(mentioned=False))

    adapter = gq.GeoQueryAdapter()
    gen = adapter._rpa_batch("kimi", ["k1", "k2", "k3"], tok, web_search=True,
                             brand="云野", aliases=[], client=object(), consec_skip=3)
    produced = []
    with pytest.raises(_CancelledFetch):
        for item in gen:
            produced.append(item)
    # 只产出第 1 个真实 cell(k1, ok);取消上抛,k2/k3 未被合成/兜底成任何 cell。
    assert [li for li, _ in produced] == [0]
    assert produced[0][1].status == "ok"
