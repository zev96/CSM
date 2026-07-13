"""R2 增量落库（崩溃安全）：monitor_run_progress 草稿表 + 两条恢复路径。

一次 baidu run 只在 adapter.fetch() 全部跑完后 save_result 落一行。除
RiskControlException（#162 已存断点）外的任何中断——硬杀 / 更新器 taskkill /
断电 / OOM / 非风控普通异常——都会丢本轮已抓完的 K 个关键词。

方案：adapter 每抓完一个关键词就把「本轮头段」flush 进 monitor_run_progress
（task_id 主键、一行一个在跑的 run）；任何中断后都能把它 materialize 成和风控
断点同构的 status="risk_control" 断点（captcha_signal_layer="interrupted"），
复用 #162 的续抓链路（头尾合并 / /resume 端点 / 前端 banner）。

覆盖：
1. 草稿表 CRUD + UPSERT + ON DELETE CASCADE（本 cycle）。
2. adapter partial_cb 每关键词 flush。
3. loop 非 ok / 异常 → materialize 断点；clean-ok / 风控 / 取消 → 清草稿。
4. 启动恢复扫描孤儿草稿 → materialize。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask


def _mk_baidu_task(n: int = 10, *, name: str = "run-progress-test") -> int:
    task = MonitorTask(
        type="baidu_keyword",
        name=name,
        target_url=f"https://www.baidu.com/s?wd={name}",
        config={"search_keywords": [f"kw{i}" for i in range(n)], "target_brand": "石头"},
    )
    return storage.create_task(task)


def _head(n: int) -> list[dict]:
    """前 n 个关键词的头段行（kw0 命中 rank5，其余未命中）。"""
    return [
        {"keyword": f"kw{i}",
         "default_first_rank": (5 if i == 0 else -1),
         "default_matched_count": (1 if i == 0 else 0),
         "default_results": [], "news_results": [], "news_present": False}
        for i in range(n)
    ]


# ── Cycle 1: 草稿表 CRUD ───────────────────────────────────────────────────

def test_save_and_get_run_progress(monitor_db: Path):
    tid = _mk_baidu_task(10)
    rows = _head(3)
    storage.save_run_progress(
        tid, next_keyword=3, keywords=rows, resume_from=0,
        total_keywords=10, search_keywords=[f"kw{i}" for i in range(10)],
        target_brand="石头",
    )
    prog = storage.get_run_progress(tid)
    assert prog is not None
    assert prog["task_id"] == tid
    assert prog["next_keyword"] == 3
    assert prog["resume_from"] == 0
    assert prog["total_keywords"] == 10
    assert prog["target_brand"] == "石头"
    assert [k["keyword"] for k in prog["keywords"]] == ["kw0", "kw1", "kw2"]
    assert prog["search_keywords"] == [f"kw{i}" for i in range(10)]


def test_get_run_progress_none_when_absent(monitor_db: Path):
    tid = _mk_baidu_task(5)
    assert storage.get_run_progress(tid) is None


def test_save_run_progress_upserts_same_task(monitor_db: Path):
    """同一 task 再 flush → 覆盖（PRIMARY KEY task_id，一行一个在跑的 run）。"""
    tid = _mk_baidu_task(10)
    storage.save_run_progress(tid, next_keyword=2, keywords=_head(2),
                              total_keywords=10)
    storage.save_run_progress(tid, next_keyword=5, keywords=_head(5),
                              total_keywords=10)
    prog = storage.get_run_progress(tid)
    assert prog["next_keyword"] == 5
    assert len(prog["keywords"]) == 5
    # 只有一行
    assert len(storage.list_run_progress()) == 1


def test_list_run_progress_returns_all_inflight(monitor_db: Path):
    t1 = _mk_baidu_task(10, name="task-a")
    t2 = _mk_baidu_task(10, name="task-b")
    storage.save_run_progress(t1, next_keyword=3, keywords=_head(3), total_keywords=10)
    storage.save_run_progress(t2, next_keyword=7, keywords=_head(7), total_keywords=10)
    progs = storage.list_run_progress()
    assert {p["task_id"] for p in progs} == {t1, t2}


def test_clear_run_progress(monitor_db: Path):
    tid = _mk_baidu_task(10)
    storage.save_run_progress(tid, next_keyword=3, keywords=_head(3), total_keywords=10)
    storage.clear_run_progress(tid)
    assert storage.get_run_progress(tid) is None
    assert storage.list_run_progress() == []


def test_clear_run_progress_absent_is_noop(monitor_db: Path):
    tid = _mk_baidu_task(5)
    storage.clear_run_progress(tid)  # 不存在也不应报错
    assert storage.get_run_progress(tid) is None


def test_run_progress_cascade_on_task_delete(monitor_db: Path):
    """删任务 → 草稿行随 ON DELETE CASCADE 一起消失（不留孤儿）。"""
    tid = _mk_baidu_task(10)
    storage.save_run_progress(tid, next_keyword=3, keywords=_head(3), total_keywords=10)
    storage.delete_task(tid)
    assert storage.get_run_progress(tid) is None


# ── Cycle 3: loop 收尾 —— materialize / 清草稿 ─────────────────────────────

def _kw_row(i: int, *, rank: int = -1, mc: int = 0) -> dict:
    return {"keyword": f"kw{i}", "default_first_rank": rank, "default_matched_count": mc,
            "default_results": [], "news_results": [], "news_present": False}


class FlushingAdapter:
    """假 baidu adapter：通过 partial_cb 把 [resume_from:flush_upto) 落进草稿，然后
    以指定方式收尾（返回 ok / 返回非 ok / 抛异常）——模拟各种中断路径。"""

    def __init__(self, *, flush_upto: int, total: int,
                 final_status: str = "ok", raise_exc: "BaseException | None" = None):
        self.flush_upto = flush_upto
        self.total = total
        self.final_status = final_status
        self.raise_exc = raise_exc

    def fetch(self, task, *, partial_cb=None, progress_cb=None,
              cancel_token=None, resume_from=0, **kw):
        rows: list[dict] = []
        for i in range(resume_from, self.flush_upto):
            rows.append(_kw_row(i))
            if partial_cb is not None:
                partial_cb(i + 1, list(rows))
        if self.raise_exc is not None:
            raise self.raise_exc
        return MonitorResult(
            task_id=task.id, checked_at=datetime.utcnow(),
            status=self.final_status, rank=-1,
            metric={"keywords": rows, "total_keywords": self.total,
                    "search_keywords": [f"kw{i}" for i in range(self.total)],
                    "target_brand": "石头"},
            error_message="" if self.final_status == "ok" else "boom",
        )


def _make_loop(adapter, events: list):
    from csm_sidecar.services.monitor_loop import MonitorLoop
    return MonitorLoop(event_sink=lambda e: events.append(e),
                       adapters={"baidu_keyword": adapter})


def test_clean_ok_run_clears_scratchpad(monitor_db: Path):
    """正常跑完 → 清干净草稿，不留孤儿（否则下次启动会被误恢复成假断点）。"""
    tid = _mk_baidu_task(10)
    task = storage.get_task(tid)
    events: list = []
    loop = _make_loop(FlushingAdapter(flush_upto=10, total=10, final_status="ok"), events)
    result = loop._run_one(task, resume_from=0)
    assert result is not None and result.status == "ok"
    assert storage.get_run_progress(tid) is None
    assert any(e.kind == "finished" for e in events)


def test_generic_exception_midscan_materializes_breakpoint(monitor_db: Path):
    """抓到第 5 个时抛异常（如 Chrome 崩）→ 用草稿 materialize 一个 interrupted 断点，
    复用续抓链路，别丢已抓完的 5 个头段。"""
    tid = _mk_baidu_task(10)
    task = storage.get_task(tid)
    events: list = []
    loop = _make_loop(
        FlushingAdapter(flush_upto=5, total=10, raise_exc=RuntimeError("chrome died")),
        events,
    )
    loop._run_one(task, resume_from=0)
    latest = storage.latest_result(tid)
    assert latest is not None and latest.status == "risk_control"
    assert latest.metric["last_resumed_keyword"] == 5
    assert latest.metric["captcha_signal_layer"] == "interrupted"
    assert [k["keyword"] for k in latest.metric["keywords"]] == [f"kw{i}" for i in range(5)]
    assert latest.metric["total_keywords"] == 10
    assert storage.get_run_progress(tid) is None
    assert storage.get_last_resumed_keyword(tid) == 5
    assert any(e.kind == "risk_control" for e in events)


def test_adapter_returns_failed_midscan_materializes_breakpoint(monitor_db: Path):
    """Gap A 主路径：Chrome 崩溃被 _fetch_with_promotion 吞成 status='failed' 返回
    （不 raise）→ runner 仍用草稿 materialize 断点，别丢头段。"""
    tid = _mk_baidu_task(10)
    task = storage.get_task(tid)
    events: list = []
    loop = _make_loop(FlushingAdapter(flush_upto=6, total=10, final_status="failed"), events)
    loop._run_one(task, resume_from=0)
    latest = storage.latest_result(tid)
    assert latest is not None and latest.status == "risk_control"
    assert latest.metric["last_resumed_keyword"] == 6
    assert latest.metric["captcha_signal_layer"] == "interrupted"
    assert [k["keyword"] for k in latest.metric["keywords"]] == [f"kw{i}" for i in range(6)]
    assert storage.get_run_progress(tid) is None


def test_cancel_midscan_clears_scratchpad_no_breakpoint(monitor_db: Path):
    """停止=放弃（保持现语义）：取消清草稿、不留断点。"""
    from csm_sidecar.services.monitor_loop import _CancelledFetch
    tid = _mk_baidu_task(10)
    task = storage.get_task(tid)
    events: list = []
    loop = _make_loop(
        FlushingAdapter(flush_upto=3, total=10, raise_exc=_CancelledFetch("stopped")),
        events,
    )
    result = loop._run_one(task, resume_from=0)
    assert result is None
    assert storage.get_run_progress(tid) is None
    assert storage.latest_result(tid) is None
    assert any(e.kind == "failed" for e in events)


def test_completed_but_failed_run_no_spurious_breakpoint(monitor_db: Path):
    """全部关键词抓完（next_keyword==total）但结果 failed → 是完整失败 run 不是中断，
    不该 materialize 一个「从 N 续抓」的假断点。"""
    tid = _mk_baidu_task(5)
    task = storage.get_task(tid)
    events: list = []
    loop = _make_loop(FlushingAdapter(flush_upto=5, total=5, final_status="failed"), events)
    loop._run_one(task, resume_from=0)
    latest = storage.latest_result(tid)
    assert latest is None or latest.status != "risk_control"
    assert storage.get_run_progress(tid) is None
    assert any(e.kind == "failed" for e in events)


def test_risk_control_clears_scratchpad(monitor_db: Path):
    """风控中断走 e.partial_keywords 权威断点，但也要清掉草稿避免孤儿被误恢复。"""
    from csm_core.monitor.drivers.risk_detector import RiskControlException, RiskSignal
    partial = [_kw_row(i) for i in range(3)]

    class RiskAdapter:
        def fetch(self, task, *, partial_cb=None, resume_from=0, **kw):
            for i in range(3):
                if partial_cb is not None:
                    partial_cb(i + 1, [_kw_row(j) for j in range(i + 1)])
            raise RiskControlException(RiskSignal(layer="dom", detail="#captcha"),
                                       progress=3, partial_keywords=partial)

    tid = _mk_baidu_task(10)
    task = storage.get_task(tid)
    events: list = []
    loop = _make_loop(RiskAdapter(), events)
    loop._run_one(task, resume_from=0)
    latest = storage.latest_result(tid)
    assert latest is not None and latest.status == "risk_control"
    assert latest.metric["captcha_signal_layer"] == "dom"  # 风控原因，不是 interrupted
    assert storage.get_run_progress(tid) is None


def test_resume_crash_supersedes_old_breakpoint_with_more_progress(monitor_db: Path):
    """resume 从 3 续、又抓完 kw3/4/5（next_keyword=6）后崩 → materialize 出和旧头段
    [0:3] 合并的 [0:6] 断点，比旧断点进度更多、取而代之。"""
    tid = _mk_baidu_task(10)
    task = storage.get_task(tid)
    head = [_kw_row(i, rank=(5 if i == 0 else -1), mc=(1 if i == 0 else 0)) for i in range(3)]
    storage.save_result(MonitorResult(
        task_id=tid, checked_at=datetime.utcnow(), status="risk_control", rank=-1,
        metric={"last_resumed_keyword": 3, "keywords": head, "total_keywords": 10,
                "search_keywords": [f"kw{i}" for i in range(10)]},
    ), alert_triggered=False)
    events: list = []
    loop = _make_loop(FlushingAdapter(flush_upto=6, total=10, final_status="failed"), events)
    loop._run_one(task, resume_from=3)
    latest = storage.latest_result(tid)
    assert latest is not None and latest.status == "risk_control"
    assert latest.metric["last_resumed_keyword"] == 6
    assert [k["keyword"] for k in latest.metric["keywords"]] == [f"kw{i}" for i in range(6)]
    assert storage.get_run_progress(tid) is None


# ── Cycle 4: 启动恢复（硬杀 Gap B）─────────────────────────────────────────
# 存活到本次启动的草稿行 = 上次进程被硬杀/崩溃时正在跑的 run（clean 终态都清草稿）。
# 逐个 materialize 成可续抓断点。注意与 loop 路径的差别：启动时任何残留草稿都
# materialize（它就意味着崩溃），不套用 loop 的 next<total 判据。

def test_startup_recovery_materializes_orphan_scratchpad(monitor_db: Path):
    from csm_sidecar.services.monitor_loop import recover_run_progress
    tid = _mk_baidu_task(10)
    # 模拟硬杀：草稿残留头段 [0:4]，没有任何终态处理器跑过
    storage.save_run_progress(
        tid, next_keyword=4, keywords=_head(4), resume_from=0,
        total_keywords=10, search_keywords=[f"kw{i}" for i in range(10)],
        target_brand="石头",
    )
    n = recover_run_progress()
    assert n == 1
    latest = storage.latest_result(tid)
    assert latest is not None and latest.status == "risk_control"
    assert latest.metric["last_resumed_keyword"] == 4
    assert latest.metric["captcha_signal_layer"] == "interrupted"
    assert [k["keyword"] for k in latest.metric["keywords"]] == [f"kw{i}" for i in range(4)]
    assert latest.metric["total_keywords"] == 10
    assert storage.get_run_progress(tid) is None  # 恢复后清掉草稿


def test_startup_recovery_no_scratchpad_is_noop(monitor_db: Path):
    from csm_sidecar.services.monitor_loop import recover_run_progress
    assert recover_run_progress() == 0


def test_startup_recovery_resume_orphan_merges_with_old_head(monitor_db: Path):
    """崩溃的 resume run：旧断点头段 [0:3] + 草稿尾段 [3:6] → 合并成 [0:6] 断点。"""
    from csm_sidecar.services.monitor_loop import recover_run_progress
    tid = _mk_baidu_task(10)
    old_head = [_kw_row(i, rank=(5 if i == 0 else -1), mc=(1 if i == 0 else 0)) for i in range(3)]
    # 旧断点 checked_at 明显早于草稿的 updated_at（草稿是崩溃前最后进度、更新）→
    # 恢复应 materialize（不是 skip）。
    storage.save_result(MonitorResult(
        task_id=tid, checked_at=datetime.utcnow() - timedelta(hours=1),
        status="risk_control", rank=-1,
        metric={"last_resumed_keyword": 3, "keywords": old_head, "total_keywords": 10,
                "search_keywords": [f"kw{i}" for i in range(10)]},
    ), alert_triggered=False)
    storage.save_run_progress(
        tid, next_keyword=6, keywords=[_kw_row(3), _kw_row(4), _kw_row(5)],
        resume_from=3, total_keywords=10,
        search_keywords=[f"kw{i}" for i in range(10)], target_brand="石头",
    )
    n = recover_run_progress()
    assert n == 1
    latest = storage.latest_result(tid)
    assert latest.metric["last_resumed_keyword"] == 6
    assert [k["keyword"] for k in latest.metric["keywords"]] == [f"kw{i}" for i in range(6)]
    assert storage.get_run_progress(tid) is None


def test_startup_recovery_multiple_orphans(monitor_db: Path):
    from csm_sidecar.services.monitor_loop import recover_run_progress
    t1 = _mk_baidu_task(10, name="orphan-a")
    t2 = _mk_baidu_task(10, name="orphan-b")
    storage.save_run_progress(t1, next_keyword=2, keywords=_head(2), total_keywords=10,
                              search_keywords=[f"kw{i}" for i in range(10)])
    storage.save_run_progress(t2, next_keyword=5, keywords=_head(5), total_keywords=10,
                              search_keywords=[f"kw{i}" for i in range(10)])
    assert recover_run_progress() == 2
    assert storage.latest_result(t1).metric["last_resumed_keyword"] == 2
    assert storage.latest_result(t2).metric["last_resumed_keyword"] == 5
    assert storage.list_run_progress() == []


def test_startup_recovery_skips_when_result_already_persisted(monitor_db: Path):
    """审查修：run 已落终态结果、只是崩在清草稿之前（checked_at >= 草稿 flush）→ 不能
    重造断点（会遮蔽真 ok 结果 + 丢它的告警），清掉草稿即可。"""
    from csm_sidecar.services.monitor_loop import recover_run_progress
    tid = _mk_baidu_task(10)
    storage.save_run_progress(tid, next_keyword=4, keywords=_head(4), total_keywords=10,
                              search_keywords=[f"kw{i}" for i in range(10)])
    # 真 ok 结果，checked_at 明显晚于草稿（run 其实跑完了、只是没来得及清草稿）
    storage.save_result(MonitorResult(
        task_id=tid, checked_at=datetime.utcnow() + timedelta(hours=1), status="ok", rank=3,
        metric={"keywords": _head(10), "total_keywords": 10}), alert_triggered=False)
    assert recover_run_progress() == 0  # 没 materialize
    assert storage.get_run_progress(tid) is None  # 草稿清掉
    assert storage.latest_result(tid).status == "ok"  # 真结果没被断点遮蔽


def test_partial_cb_strips_blank_keywords(monitor_db: Path):
    """审查修：草稿的 total/search_keywords 与适配器同源地 strip+过滤空白项，否则进度
    分母虚高、合并时 raw 名对不上 stripped 名会漏配。"""
    task = MonitorTask(
        type="baidu_keyword", name="blank-kw", target_url="https://baidu.com/blank",
        config={"search_keywords": ["扫地机", "  ", "洗地机", ""], "target_brand": "石头"},
    )
    tid = storage.create_task(task)
    task.id = tid
    events: list = []
    # 抓 1 个后崩 → materialize 断点，其 total/search_keywords 应为 strip 后的 2
    loop = _make_loop(FlushingAdapter(flush_upto=1, total=2, raise_exc=RuntimeError("x")), events)
    loop._run_one(task, resume_from=0)
    latest = storage.latest_result(tid)
    assert latest is not None and latest.status == "risk_control"
    assert latest.metric["total_keywords"] == 2  # 不是 4（含 2 个空白）
    assert latest.metric["search_keywords"] == ["扫地机", "洗地机"]


def test_override_run_does_not_clear_foreign_scratchpad(monitor_db: Path):
    """审查修（所有权）：单关键词 override「启动监测」不拥有草稿 → clean-ok 收尾不能
    误删别的（崩溃残留）run 的草稿。"""
    tid = _mk_baidu_task(10)
    # 预置一条崩溃残留草稿（上次全量 run 硬杀、又恰逢启动恢复失败留下的）
    storage.save_run_progress(tid, next_keyword=4, keywords=_head(4), total_keywords=10,
                              search_keywords=[f"kw{i}" for i in range(10)])
    task = storage.get_task(tid)
    cfg = dict(task.config)
    cfg["_keyword_override"] = "kw0"
    cfg["search_keywords"] = ["kw0"]
    task.config = cfg
    events: list = []
    loop = _make_loop(FlushingAdapter(flush_upto=1, total=1, final_status="ok"), events)
    loop._run_one(task, resume_from=0)
    # 草稿仍在、未被 override run 误删
    prog = storage.get_run_progress(tid)
    assert prog is not None and prog["next_keyword"] == 4


# ── 收尾-2：save→clear 原子化 + materialize 单调时钟 ───────────────────────

def test_save_result_atomic_clear_progress(monitor_db: Path):
    """审查修（2a）：save_result 落断点 + 清草稿在**一个事务**里完成，硬杀夹在两语句
    之间不会留残草稿 → 下次启动重造一条重复断点。"""
    tid = _mk_baidu_task(10)
    storage.save_run_progress(tid, next_keyword=4, keywords=_head(4), total_keywords=10,
                              search_keywords=[f"kw{i}" for i in range(10)])
    bp = MonitorResult(task_id=tid, checked_at=datetime.utcnow(), status="risk_control",
                       rank=-1, metric={"last_resumed_keyword": 4, "keywords": _head(4)},
                       error_message="")
    storage.save_result(bp, clear_progress_task_id=tid)
    assert storage.get_run_progress(tid) is None            # 同事务清掉
    assert storage.latest_result(tid).status == "risk_control"  # 断点已落


def test_startup_recovery_clamps_checked_at_above_latest_on_backward_clock(monitor_db: Path):
    """审查修（2c）：时钟倒退时，materialize 的断点 checked_at 须钳到 > 现有最新结果，
    否则 ORDER BY checked_at DESC 会让**旧断点**排前面、续抓退回更早位置。"""
    from csm_sidecar.services.monitor_loop import recover_run_progress
    tid = _mk_baidu_task(10)
    t0 = datetime.utcnow() - timedelta(hours=2)   # 旧断点（更早一次中断）
    storage.save_result(MonitorResult(
        task_id=tid, checked_at=t0, status="risk_control", rank=-1,
        metric={"last_resumed_keyword": 2, "keywords": _head(2), "total_keywords": 10,
                "search_keywords": [f"kw{i}" for i in range(10)]}), alert_triggered=False)
    # 之后的 run flush 了更多进度（草稿 updated_at = 真 now > t0，故不触发 skip 守卫）
    storage.save_run_progress(tid, next_keyword=5, keywords=_head(5), resume_from=0,
                              total_keywords=10, search_keywords=[f"kw{i}" for i in range(10)])
    # 时钟倒退：materialize 用一个 < t0 的 now
    recover_run_progress(now=t0 - timedelta(hours=1))
    latest = storage.latest_result(tid)
    # 尽管时钟倒退，materialize 的断点(next=5)仍排在旧断点(next=2)之上
    assert latest.metric["last_resumed_keyword"] == 5
